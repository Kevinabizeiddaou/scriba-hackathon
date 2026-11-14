"""The one seam between the Desk overlay and Scriba.

Every call into Scriba's code goes through ``ScribaGateway``. Routes and the
pure modules never import Scriba, so they are tested with a fake gateway and
no Scriba checkout. Scriba modules are imported inside the methods: importing
this file needs nothing but the standard library.

Read-only. Nothing here sends mail or writes to a calendar.
"""
from __future__ import annotations

import contextvars
import datetime as dt
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List, Mapping, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .availability import Busy


@dataclass(frozen=True)
class DeskUser:
    id: int
    email: str


# The user a background worker is acting for. A request carries a session; a
# worker thread has none, so it names the user here and every status read
# takes that identity explicitly (never another user's, never "whoever is
# signed in").
_acting: contextvars.ContextVar[Optional[DeskUser]] = contextvars.ContextVar("desk_acting", default=None)


@contextmanager
def acting_as(user: Optional[DeskUser]) -> Iterator[Optional[DeskUser]]:
    token = _acting.set(user)
    try:
        yield user
    finally:
        _acting.reset(token)


def acting_user() -> Optional[DeskUser]:
    return _acting.get()


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

    def user_for_email(self, email: str) -> Optional[DeskUser]:
        """The Scriba user behind an account address (chat passes the address)."""
        from app.db import get_user_by_email

        row = get_user_by_email(email) if email else None
        if not row or row.get("id") is None:
            return None
        return DeskUser(id=int(row["id"]), email=str(row.get("email") or email).strip().lower())

    def scriba_commit(self) -> Optional[str]:
        import os

        return (os.environ.get("SCRIBA_COMMIT") or os.environ.get("GIT_COMMIT") or "").strip() or None

    def is_production(self) -> bool:
        """Scriba's own test for a production process (APP_ENV and friends)."""
        try:
            from app.env_utils import is_production

            return bool(is_production())
        except Exception:
            return True     # unknown is treated as production: nothing optional starts

    def session_email(self, request: Any) -> Optional[str]:
        """The address of the signed-in user, or None. Never raises."""
        acting = _acting.get()
        if acting is not None:
            return acting.email
        try:
            user = request.app.state.provider_status_runtime.current_user()
        except Exception:
            return None
        if not user:
            return None
        return str(user.get("_active_email") or user.get("email") or "").strip().lower() or None

    # ── connections ─────────────────────────────────────────────────────────
    def provider_status(self, request: Any) -> Dict[str, Any]:
        """The payload behind ``GET /providers/status`` for the session user,
        or for the user a worker is acting for."""
        acting = _acting.get()
        if acting is not None:
            return self.provider_status_for(acting)
        runtime = request.app.state.provider_status_runtime
        user = runtime.current_user()
        if user is None:
            return runtime.anonymous_payload()
        return runtime.status_payload(user)

    def provider_status_for(self, user: DeskUser) -> Dict[str, Any]:
        """The same status with the identity passed explicitly: Scriba's own
        aggregation, with no session involved."""
        from app.provider_status_domain_adapter import modular_status_payload

        return modular_status_payload(user_id=user.id, account_email=user.email)

    def acting_status(self) -> Optional[Dict[str, Any]]:
        acting = _acting.get()
        return self.provider_status_for(acting) if acting is not None else None

    # ── claims: Scriba's idempotency ledger for backend side effects ────────
    def claim_receipt(self, user_id: int, key: str, kind: str) -> Dict[str, Any]:
        """``automation_action_receipts``: UNIQUE (user_id, action_key)."""
        from app import desktop_repository

        return desktop_repository.claim_action_receipt(
            user_id=int(user_id), action_key=key, action_type=kind)

    def finish_receipt(self, receipt_id: Any, status: str, object_id: Optional[str] = None) -> None:
        from app import desktop_repository

        desktop_repository.finish_action_receipt(
            receipt_id=int(receipt_id), status=status, object_id=object_id,
            verified=status == "succeeded")

    def enrolled_users(self, addresses: List[str]) -> List[DeskUser]:
        """The Scriba users behind the addresses a worker was told to serve."""
        found = []
        for address in addresses:
            user = self.user_for_email(str(address).strip().lower())
            if user is not None:
                found.append(user)
        return found

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

    def list_sent(self, request: Any, user: DeskUser, provider: str,
                  mailbox: Optional[str] = None) -> List[Dict[str, Any]]:
        """The payload behind ``GET /emails/sent``: what the user has sent."""
        payload = _as_dict(request.app.state.email_read_runtime.sent_payload(
            account_email=user.email, provider=provider, limit=200, offset=0, mailbox=mailbox))
        return [row for row in (payload.get("messages") or []) if isinstance(row, dict)]

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

    # ── workflow runs: Scriba chat conversations and action cards ───────────
    @staticmethod
    def _run_of(row: Optional[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
        meta = _as_dict((row or {}).get("metadata")).get("desk_run") if row else None
        if not row or not isinstance(meta, dict) or not meta.get("key"):
            return None
        return {"id": int(row["id"]), "meta": meta}

    def list_runs(self, user: DeskUser, limit: int = 50,
                  include_evaluation: bool = False) -> List[Dict[str, Any]]:
        from app import chat_repository

        runs = [self._run_of(row) for row in chat_repository.list_conversations(user.id, limit=200)]
        return [run for run in runs
                if run and (include_evaluation or not run["meta"].get("evaluation"))][:limit]

    # ── evidence: append-only events on the run's conversation ──────────────
    def record_event(self, user: DeskUser, run: Mapping[str, Any], item: Dict[str, Any],
                     summary: str) -> None:
        """One system message per event. The text is a plain summary; the
        structured event is in the message metadata. Never message content."""
        from app import chat_repository

        chat_repository.create_message(
            conversation_id=int(run["id"]), user_id=user.id, role="system", content=summary,
            metadata={"desk_event": item})

    def run_events(self, user: DeskUser, run: Mapping[str, Any]) -> List[Dict[str, Any]]:
        from app import chat_repository

        rows = chat_repository.list_messages(int(run["id"]), user_id=user.id, limit=500)
        events = []
        for row in rows:
            item = _as_dict(row.get("metadata")).get("desk_event")
            if isinstance(item, dict) and item.get("kind"):
                events.append(item)
        return events

    def find_run(self, user: DeskUser, key: str) -> Optional[Dict[str, Any]]:
        return next((run for run in self.list_runs(user, 200, include_evaluation=True)
                     if run["meta"].get("key") == key), None)

    def get_run(self, user: DeskUser, run_id: int) -> Optional[Dict[str, Any]]:
        """A run only if it belongs to this user (Scriba's repository scopes by user)."""
        from app import chat_repository

        return self._run_of(chat_repository.get_conversation(int(run_id), user_id=user.id))

    def open_run(self, user: DeskUser, *, title: str, meta: Dict[str, Any],
                 summary: str) -> Dict[str, Any]:
        """A Scriba chat conversation holding the run, with one assistant
        message that the proposed action cards hang from."""
        from app import chat_repository

        conversation = chat_repository.create_conversation(
            user_id=user.id, title=title, metadata={"desk_run": meta})
        message = chat_repository.create_message(
            conversation_id=int(conversation["id"]), user_id=user.id, role="assistant", content=summary)
        meta["message_id"] = int(message["id"])
        return {"id": int(conversation["id"]), "meta": meta}

    def propose_action(self, user: DeskUser, run: Dict[str, Any], *, tool_name: str,
                       tool_input: Dict[str, Any], email_id: Optional[str],
                       thread_id: Optional[str], provider: Optional[str]) -> Optional[Dict[str, Any]]:
        """Create an action card through Scriba's own card path: its
        validation gate, provider checks and idempotent card creation."""
        from app import chat_repository, chat_service

        from .chat_scope import trusted_recipients
        from .workflow import sender_address

        message_id = run["meta"].get("message_id")
        if not message_id:
            messages = chat_repository.list_messages(run["id"], user_id=user.id, limit=5)
            message_id = next((m["id"] for m in messages if m.get("role") == "assistant"), None)
        # The one address the Desk vouches for on its own cards: the sender of
        # the message the run is about, taken from its From header.
        with trusted_recipients([sender_address(str(run["meta"].get("from_addr") or ""))]):
            return chat_service._handle_tool_call(
                account_email=user.email, user_id=user.id, conversation_id=run["id"],
                message_id=int(message_id), tool_name=tool_name, tool_input=dict(tool_input),
                provider_status=chat_service._safe_provider_status(user.email),
                email_id=email_id, thread_id=thread_id, provider=provider, user_message="",
            )

    def run_cards(self, user: DeskUser, run: Dict[str, Any]) -> List[Dict[str, Any]]:
        from app import chat_repository

        rows = chat_repository.list_tool_calls_for_conversation(run["id"], user_id=user.id)
        return [chat_repository.serialize_tool_call(row) for row in rows]

    def extract_meeting(self, user: DeskUser, item: Mapping[str, Any],
                        timezone: str) -> Optional[Dict[str, Any]]:
        """Scriba's own email-plan extraction (its model, its prompt). Returns
        the plan when it names a calendar request (``calendar_action`` create,
        reschedule or cancel). None when the model is unavailable or says
        nothing usable: the workflow then proposes no event rather than
        guessing a time."""
        from app import llm_client

        try:
            plan = llm_client.extract_email_plan(
                subject=str(item.get("subject") or ""), from_addr=str(item.get("from_addr") or ""),
                body=str(item.get("body") or item.get("snippet") or ""), account_email=user.email,
                user_name=None, timezone=timezone, thread_context=[], attachment_context={},
            )
        except Exception:
            return None
        if not isinstance(plan, dict) or str(plan.get("calendar_action") or "").lower() not in (
                "create", "reschedule", "cancel"):
            return None
        return plan

    def model_configured(self) -> bool:
        """Whether Scriba's model gateway has a usable configuration."""
        try:
            from app import llm_client

            return bool(llm_client._ai_configured())
        except Exception:
            return False

    @contextmanager
    def model_usage(self) -> Iterator[List[Dict[str, Any]]]:
        """Collect the model calls made inside the block.

        The numbers are Scriba's own: its telemetry record for each call, and
        its effective-dated price table for the cost. A call with no measured
        usage or no known price has ``costUsd: None``. Nothing is estimated.
        """
        calls: List[Dict[str, Any]] = []
        token = _usage_sink.set(calls)
        try:
            _install_usage_tap()
            yield calls
        finally:
            _usage_sink.reset(token)

    def calendar_events(self, user: DeskUser, start: dt.datetime,
                        end: dt.datetime) -> List[Dict[str, Any]]:
        """Scriba's mirrored calendar (the list behind ``GET /calendar/events``),
        both providers, for finding the meeting a change request is about."""
        from app.agenda_service import list_calendar_meetings

        payload = list_calendar_meetings(account_email=user.email, range_start=start.isoformat(),
                                         range_end=end.isoformat()) or {}
        return [m for m in (payload.get("meetings") or []) if isinstance(m, dict)]

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


_usage_sink: contextvars.ContextVar[Optional[List[Dict[str, Any]]]] = contextvars.ContextVar(
    "desk_usage_sink", default=None)
_usage_tap = {"installed": False}


def _install_usage_tap() -> None:
    """Listen to Scriba's AI telemetry. Scriba's own recording is unchanged."""
    if _usage_tap["installed"]:
        return
    try:
        from app.ai import pricing, telemetry
    except Exception:
        return
    original = telemetry.record

    def record(record_obj: Any) -> None:
        sink = _usage_sink.get()
        if sink is not None:
            try:
                cost = telemetry._cost_fields(record_obj)
                prompt = getattr(record_obj, "prompt_tokens", None)
                cached = getattr(record_obj, "cached_tokens", None)
                written = getattr(record_obj, "cache_write_tokens", None)
                measured = prompt is not None and not getattr(record_obj, "usage_estimated", False)
                sink.append({
                    "model": getattr(record_obj, "model", None),
                    "feature": getattr(record_obj, "feature", None),
                    "success": bool(getattr(record_obj, "success", False)),
                    # Uncached input only; cached input is billed at another rate.
                    "inputTokens": max(0, int(prompt) - int(cached or 0) - int(written or 0))
                    if measured else None,
                    "outputTokens": getattr(record_obj, "completion_tokens", None) if measured else None,
                    "cachedInputTokens": cached if measured else None,
                    "latencyMs": getattr(record_obj, "latency_ms", None),
                    "costUsd": float(cost["cost_usd"]) if cost.get("cost_usd") is not None else None,
                    "costStatus": cost.get("cost_status"),
                    "pricingVersion": cost.get("pricing_version"),
                    "priceSource": pricing.PRICING_SOURCE,
                })
            except Exception:
                pass
        return original(record_obj)

    telemetry.record = record
    _usage_tap["installed"] = True


def _as_dict(value: Any) -> Dict[str, Any]:
    """Scriba runtimes return either a dict or a JSON response object."""
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        import json

        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
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
