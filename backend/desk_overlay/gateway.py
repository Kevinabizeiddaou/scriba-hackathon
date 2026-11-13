"""The one seam between the Desk overlay and Scriba.

Every call into Scriba's code goes through ``ScribaGateway``. Routes and the
pure modules never import Scriba, so they are tested with a fake gateway and
no Scriba checkout. Scriba modules are imported inside the methods: importing
this file needs nothing but the standard library.

Read-only. Nothing here sends mail or writes to a calendar.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .availability import Busy


@dataclass(frozen=True)
class DeskUser:
    id: int
    email: str


class CalendarReadError(Exception):
    """A calendar could not be read. ``code`` is safe to show to a client."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


def _graph_datetime(value: Mapping[str, Any]) -> Optional[dt.datetime]:
    """A Microsoft Graph dateTimeTimeZone to an aware datetime.

    Graph returns calendar times without an offset plus a separate zone name,
    UTC unless the request asked otherwise. The value is read in ITS zone,
    never in the user's.
    """
    text = str((value or {}).get("dateTime") or "").strip()
    if not text:
        return None
    if "." in text:  # Graph sends seven fractional digits; Python accepts six.
        head, _, fraction = text.partition(".")
        text = f"{head}.{fraction[:6]}"
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed
    zone_name = str((value or {}).get("timeZone") or "UTC").strip() or "UTC"
    try:
        zone: dt.tzinfo = ZoneInfo(zone_name)
    except Exception:
        zone = dt.timezone.utc
    return parsed.replace(tzinfo=zone)


class ScribaGateway:
    """Scriba at commit 3ae3a2aa. Each method names the Scriba code it reuses."""

    # ── identity ────────────────────────────────────────────────────────────
    def current_user(self, request: Any) -> DeskUser:
        """Scriba's own route dependency: 401/403 exactly as its routers do."""
        from apps.api.auth import authenticated_user

        user = authenticated_user(request, requested_account=request.query_params.get("account"))
        return DeskUser(id=user.id, email=user.email)

    def scriba_commit(self) -> Optional[str]:
        import os

        return (os.environ.get("SCRIBA_COMMIT") or os.environ.get("GIT_COMMIT") or "").strip() or None

    # ── connections ─────────────────────────────────────────────────────────
    def provider_status(self, request: Any) -> Dict[str, Any]:
        """The payload behind ``GET /providers/status`` for the session user."""
        runtime = request.app.state.provider_status_runtime
        user = runtime.current_user()
        if user is None:
            return runtime.anonymous_payload()
        return runtime.status_payload(user)

    # ── mail ────────────────────────────────────────────────────────────────
    def list_emails(self, request: Any, user: DeskUser, *, provider: str, limit: int,
                    mailbox: Optional[str] = None) -> Dict[str, Any]:
        """The payload behind ``GET /emails`` for one provider."""
        return request.app.state.email_read_runtime.list_payload(
            account_email=user.email,
            db_user_id=user.id,
            provider=provider,
            minutes=None,
            q="",
            limit=limit,
            cursor=None,
            mailbox=mailbox,
        )

    def classify(self, *, from_addr: str, subject: str, body: str) -> Dict[str, Any]:
        """Scriba's reply classifier: bulk and automated mail, questions,
        direct requests, meeting requests, urgency."""
        from app.reply_draft_policy import classify_reply_candidate

        return classify_reply_candidate(from_addr=from_addr, subject=subject, body=body)

    # ── preferences ─────────────────────────────────────────────────────────
    def preferences(self, user: DeskUser) -> Dict[str, Any]:
        """Time zone, working hours, weekdays, buffer and default duration."""
        from app.preferences_service import get_user_preferences

        return get_user_preferences(user.email) or {}

    # ── briefing inputs ─────────────────────────────────────────────────────
    def agenda_today(self, request: Any, user: DeskUser) -> Dict[str, Any]:
        """The payload behind ``GET /agenda/today`` (Scriba's synced calendar)."""
        return request.app.state.calendar_read_runtime.agenda_today(
            account_email=user.email, provider=None) or {}

    def open_tasks(self, request: Any, user: DeskUser, limit: int) -> List[Dict[str, Any]]:
        """The payload behind ``GET /tasks``, open tasks first."""
        payload = _as_dict(request.app.state.tasks_runtime.list_tasks(
            account=None, provider=None, limit=limit, order="actionable"))
        return [task for task in (payload.get("tasks") or []) if isinstance(task, dict)]

    def upcoming_reminders(self, user: DeskUser, limit: int) -> List[Dict[str, Any]]:
        """The payload behind ``GET /reminders/upcoming``."""
        from apps.api import reminders as reminders_api

        records = reminders_api.UpcomingReminders(reminders_api.reminder_repository()).execute(
            user.id, limit=limit, provider=None)
        payload = _as_dict(reminders_api.upcoming_reminders_response(user.email, records))
        return [item for item in (payload.get("reminders") or []) if isinstance(item, dict)]

    # ── calendars ───────────────────────────────────────────────────────────
    def google_busy(self, user: DeskUser, account: str, start: dt.datetime,
                    end: dt.datetime, timezone: str) -> List[Busy]:
        """Busy time on one Google account's primary calendar, from Google's
        free/busy query: the same call Scriba's ``is_slot_free`` makes, with
        that account's own credentials."""
        from app import calendar_client
        from app.gmail_client import GmailCredentialsMissing

        try:
            service = calendar_client.calendar_service(user.email, provider_account_id=account)
        except calendar_client.CalendarAccessError as exc:
            raise CalendarReadError("permission_missing", str(exc)) from exc
        except GmailCredentialsMissing as exc:
            raise CalendarReadError("reconnect_required", str(exc)) from exc
        try:
            response = service.freebusy().query(body={
                "timeMin": start.isoformat(),
                "timeMax": end.isoformat(),
                "timeZone": timezone,
                "items": [{"id": "primary"}],
            }).execute()
        except Exception as exc:  # provider or network failure
            raise CalendarReadError(_google_error_code(exc), type(exc).__name__) from exc

        primary = ((response.get("calendars") or {}).get("primary") or {})
        if primary.get("errors"):
            raise CalendarReadError("provider_error", "free/busy reported an error")
        busy: List[Busy] = []
        for window in primary.get("busy") or []:
            window_start = calendar_client.parse_datetime(window.get("start"), timezone)
            window_end = calendar_client.parse_datetime(window.get("end"), timezone)
            if window_start and window_end and window_end > window_start:
                busy.append(Busy(window_start, window_end, "google", account))
        return busy

    def outlook_busy(self, user: DeskUser, account: str, start: dt.datetime,
                     end: dt.datetime) -> List[Busy]:
        """Busy time on the user's Outlook calendar, from Graph's calendar
        view through Scriba's Outlook client and its stored token."""
        from app import outlook_client

        token = outlook_client.get_access_token(user.id)
        if not token:
            raise CalendarReadError("reconnect_required", "no Outlook access token")
        start_utc = start.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        end_utc = end.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        path = (
            "/me/calendarView"
            f"?startDateTime={quote(start_utc, safe=':-T.')}&endDateTime={quote(end_utc, safe=':-T.')}"
            "&$top=250&$select=id,subject,start,end,isCancelled,isAllDay,showAs"
            "&$orderby=start/dateTime"
        )
        try:
            data = outlook_client.graph_get(path, token)
        except Exception as exc:
            raise CalendarReadError(_graph_error_code(exc), type(exc).__name__) from exc
        if data.get("@odata.nextLink"):
            # More events than one page: an incomplete read must not look free.
            raise CalendarReadError("range_too_large", "narrow the range")

        busy: List[Busy] = []
        for event in data.get("value") or []:
            if event.get("isCancelled"):
                continue
            # Outlook's own availability marker. Free and working-elsewhere
            # time does not block a meeting.
            if str(event.get("showAs") or "busy").lower() in ("free", "workingelsewhere"):
                continue
            event_start = _graph_datetime(event.get("start") or {})
            event_end = _graph_datetime(event.get("end") or {})
            if event_start and event_end and event_end > event_start:
                busy.append(Busy(event_start, event_end, "outlook", account,
                                 title=(event.get("subject") or None)))
        return busy


def _as_dict(value: Any) -> Dict[str, Any]:
    """Scriba runtimes return either a dict or a JSON response object."""
    if isinstance(value, dict):
        return value
    body = getattr(value, "body", None)
    if body:
        import json

        try:
            parsed = json.loads(body)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _google_error_code(exc: Exception) -> str:
    status = getattr(getattr(exc, "resp", None), "status", None)
    try:
        status = int(status) if status is not None else None
    except (TypeError, ValueError):
        status = None
    if status in (401, 403):
        return "reconnect_required" if status == 401 else "permission_missing"
    if type(exc).__name__ in ("RefreshError", "GmailCredentialsMissing"):
        return "reconnect_required"
    return "provider_error"


def _graph_error_code(exc: Exception) -> str:
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status == 401:
        return "reconnect_required"
    if status == 403:
        return "permission_missing"
    return "provider_error"
