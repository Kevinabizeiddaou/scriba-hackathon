"""The Desk's four capabilities, derived from Scriba's provider status. Pure.

Scriba's status payload also describes integrations the Desk excludes. They
are dropped here, on the server, so they never reach a Desk client.
(The frontend has the same mapping in ``frontend/src/lib/connections.ts``.)
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

_SOURCES = (
    ("gmail", "gmail", "google", "Gmail", "/auth/login"),
    ("google_calendar", "google_calendar", "google", "Google Calendar", "/auth/login"),
    ("outlook_mail", "outlook", "microsoft", "Outlook Mail", "/auth/outlook/login"),
    ("outlook_calendar", "outlook_calendar", "microsoft", "Outlook Calendar", "/auth/outlook/login"),
)
MAIL_PROVIDERS = {"gmail": "gmail", "outlook": "outlook_mail"}
CALENDAR_PROVIDERS = {"google": "google_calendar", "outlook": "outlook_calendar"}


def _state(row: Optional[Mapping[str, Any]]) -> str:
    if not row:
        return "unavailable"
    if row.get("available") is False or row.get("configured") is False:
        return "unavailable"
    if row.get("reconnectRequired") or row.get("status") == "reconnect_required":
        return "reconnect_required"
    if row.get("connected") is True:
        return "connected"
    return "disconnected"


def capabilities_from(status: Optional[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    providers = (status or {}).get("providers") or {}
    out: List[Dict[str, Any]] = []
    for capability_id, key, vendor, label, login_path in _SOURCES:
        row = providers.get(key) if isinstance(providers, Mapping) else None
        row = row if isinstance(row, Mapping) else None
        out.append({
            "id": capability_id,
            "vendor": vendor,
            "label": label,
            "state": _state(row),
            "email": (row or {}).get("email"),
            "reason": (row or {}).get("reason"),
            "loginPath": (row or {}).get("loginPath") or login_path,
        })
    return out


def state_of(capabilities: List[Mapping[str, Any]], capability_id: str) -> str:
    for item in capabilities:
        if item.get("id") == capability_id:
            return str(item.get("state"))
    return "unavailable"


def secretary_ready(capabilities: List[Mapping[str, Any]]) -> bool:
    """One usable mailbox and one usable calendar, from either vendor."""
    connected = {item["id"] for item in capabilities if item.get("state") == "connected"}
    return bool(connected & {"gmail", "outlook_mail"}) and bool(
        connected & {"google_calendar", "outlook_calendar"}
    )


def google_calendar_accounts(status: Optional[Mapping[str, Any]]) -> List[str]:
    """Addresses of the user's connected Google accounts, primary first."""
    accounts = (status or {}).get("gmailAccounts") or []
    ordered = sorted(
        (a for a in accounts if isinstance(a, Mapping) and a.get("connected")),
        key=lambda a: 0 if a.get("isPrimary") else 1,
    )
    seen: List[str] = []
    for account in ordered:
        address = str(account.get("providerAccountId") or account.get("email") or "").strip().lower()
        if address and address not in seen:
            seen.append(address)
    return seen
