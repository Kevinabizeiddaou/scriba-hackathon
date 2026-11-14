"""The fictional office: one executive, the people around her, her accounts,
calendars, tasks, reminders, mail history and the replies she is waiting for.

Pure data. ``build_office(day, seed)`` returns a JSON-serialisable
specification with deterministic ids; the sandbox server turns it into the
Desk's isolated provider world, and the oracle reads the same specification
to know who is who. Nothing here is copied from a real mailbox: every person
is invented and every address is under the reserved ``.example`` domain.

The office is anchored on a Monday (``day``). ``D+n`` below means ``n`` days
after it, in the office's time zone.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

SPEC_VERSION = 1
DEFAULT_DAY = "2026-11-16"          # a Monday
DEFAULT_SEED = 7
TIMEZONE = "Europe/Paris"

# The Scriba account the Desk is signed in with on the seeded backend. It is
# Scriba's own seeded test user; the executive's mail accounts are below.
SCRIBA_USER = "alice@example.com"

ORG = {
    "name": "Meridian Freight Partners",
    "domain": "meridianfreight.example",
    "business": "Mid-sized European freight forwarder: sea, road and cold-chain lanes.",
    "office": "Paris",
}

EXECUTIVE = {
    "id": "exec",
    "name": "Layla Mansour",
    "title": "Chief Executive Officer",
    "gmail": "layla.mansour@meridianfreight.example",          # Google Workspace, primary
    "gmail_advisory": "layla@mansour-advisory.example",          # second Google account (advisory work)
    "outlook": "layla.mansour@portalliance.example",            # Microsoft 365 (board seat at Port Alliance)
}

ASSISTANT_ROLE = {
    "title": "Executive Assistant to the CEO",
    "status": "The role the Desk performs in this simulation.",
    "duties": [
        "Read every message that reaches the CEO's three mailboxes",
        "Decide what each one needs and how urgent it is",
        "Arrange, move and cancel meetings across the Google and Outlook calendars",
        "Answer or draft answers in the original thread, from the mailbox that received it",
        "Record tasks, deadlines and reminders",
        "Chase replies that have not come",
        "Brief the CEO on what was handled, what is pending and what is overdue",
    ],
}

# id -> person. ``kind`` is how the office relates to them.
PEOPLE: List[Dict[str, str]] = [
    # internal colleagues
    {"id": "omar", "name": "Omar Haddad", "title": "Chief Financial Officer", "kind": "colleague",
     "email": "omar.haddad@meridianfreight.example"},
    {"id": "priya", "name": "Priya Nair", "title": "Chief Operating Officer", "kind": "colleague",
     "email": "priya.nair@meridianfreight.example"},
    {"id": "jonas", "name": "Jonas Weber", "title": "Head of Sales", "kind": "colleague",
     "email": "jonas.weber@meridianfreight.example"},
    {"id": "elena", "name": "Elena Petrova", "title": "General Counsel", "kind": "colleague",
     "email": "elena.petrova@meridianfreight.example"},
    {"id": "sam", "name": "Sam Okoye", "title": "Chief of Staff", "kind": "colleague",
     "email": "sam.okoye@meridianfreight.example"},
    # external clients
    {"id": "greta", "name": "Greta Lindqvist", "title": "VP Supply Chain, Nordlicht Retail", "kind": "client",
     "email": "greta.lindqvist@nordlicht-retail.example"},
    {"id": "daniel", "name": "Daniel Okafor", "title": "Procurement Director, Atlas Pharma", "kind": "client",
     "email": "daniel.okafor@atlaspharma.example"},
    {"id": "mei", "name": "Mei Tanaka", "title": "Logistics Lead, Brightwave Foods", "kind": "client",
     "email": "mei.tanaka@brightwavefoods.example"},
    # suppliers and partners
    {"id": "karim", "name": "Karim Saad", "title": "Account Manager, Harbor Crane Services", "kind": "supplier",
     "email": "karim.saad@harborcrane.example"},
    {"id": "ingrid", "name": "Ingrid Solberg", "title": "Partnerships Director, Bluewater Shipping",
     "kind": "partner", "email": "ingrid.solberg@bluewatershipping.example"},
    {"id": "tomas", "name": "Tomas Vega", "title": "Broker, Kestrel Insurance", "kind": "supplier",
     "email": "tomas.vega@kestrelinsurance.example"},
    {"id": "rafael", "name": "Rafael Costa", "title": "Audit Manager, Lumen Audit LLP", "kind": "supplier",
     "email": "rafael.costa@lumenaudit.example"},
    {"id": "hannah", "name": "Hannah Schmidt", "title": "Board Secretary, Port Alliance", "kind": "partner",
     "email": "hannah.schmidt@portalliance.example"},
    {"id": "nora", "name": "Nora Aziz", "title": "Founder, Verde Mobility", "kind": "advisory",
     "email": "nora.aziz@verdemobility.example"},
    {"id": "yusuf", "name": "Yusuf Demir", "title": "Director, Anatolia Cargo", "kind": "prospect",
     "email": "yusuf.demir@anatoliacargo.example"},
    # senders that are not people
    {"id": "newsletter", "name": "Freight Weekly", "title": "Trade newsletter", "kind": "automated",
     "email": "newsletter@freightweekly.example"},
    {"id": "travel", "name": "TravelHub Notifications", "title": "Booking system", "kind": "automated",
     "email": "no-reply@travelhub.example"},
    {"id": "stranger", "name": "QuickLeads Outreach", "title": "Unknown sender", "kind": "unknown",
     "email": "promo@quickleads.example"},
    {"id": "claire", "name": "Claire Dubois", "title": "Avocate, Cabinet Dubois (opposing counsel)",
     "kind": "unknown", "email": "claire.dubois@cabinet-dubois.example"},
]

PREFERENCES = {
    "timezone": TIMEZONE,
    "workday_start_time": "09:00:00",
    "workday_end_time": "18:00:00",
    "preferred_weekdays": [0, 1, 2, 3, 4],
    "meeting_buffer_minutes": 0,
    "default_meeting_duration_minutes": 30,
}


def person(person_id: str) -> Dict[str, str]:
    if person_id == "exec":
        return {"id": "exec", "name": EXECUTIVE["name"], "title": EXECUTIVE["title"],
                "kind": "executive", "email": EXECUTIVE["gmail"]}
    for entry in PEOPLE:
        if entry["id"] == person_id:
            return entry
    raise KeyError(f"unknown person: {person_id}")


def address(person_id: str) -> str:
    return person(person_id)["email"]


def from_header(person_id: str) -> str:
    who = person(person_id)
    return f"{who['name']} <{who['email']}>"


class OfficeClock:
    """Dates of the simulated week, in the office's zone."""

    def __init__(self, day: str = DEFAULT_DAY, timezone: str = TIMEZONE) -> None:
        self.zone = ZoneInfo(timezone)
        self.timezone = timezone
        self.day = dt.date.fromisoformat(day)
        if self.day.weekday() != 0:
            raise ValueError("the simulated week must start on a Monday")

    def at(self, offset_days: int, clock: str) -> dt.datetime:
        hour, minute = (int(part) for part in clock.split(":"))
        return dt.datetime.combine(self.day + dt.timedelta(days=offset_days),
                                   dt.time(hour, minute), tzinfo=self.zone)

    def iso(self, offset_days: int, clock: str) -> str:
        return self.at(offset_days, clock).isoformat()

    def date(self, offset_days: int) -> dt.date:
        return self.day + dt.timedelta(days=offset_days)

    def written(self, offset_days: int) -> str:
        """"19 November", the way a person writes a date in an email."""
        day = self.date(offset_days)
        return f"{day.day} {day.strftime('%B')}"

    def weekday(self, offset_days: int) -> str:
        return self.date(offset_days).strftime("%A")


def _event(clock: OfficeClock, event_id: str, provider: str, account: str, title: str,
           offset: int, start: str, end: str, attendees: List[str],
           organizer: Optional[str] = None, location: Optional[str] = None) -> Dict[str, Any]:
    return {"id": event_id, "provider": provider, "account": account, "title": title,
            "start": clock.iso(offset, start), "end": clock.iso(offset, end),
            "attendees": [address(a) for a in attendees],
            "organizer": address(organizer) if organizer else account, "location": location}


def build_office(day: str = DEFAULT_DAY, seed: int = DEFAULT_SEED) -> Dict[str, Any]:
    """The office as it stands at 08:00 on the simulated Monday."""
    clock = OfficeClock(day)
    work, advisory, board = EXECUTIVE["gmail"], EXECUTIVE["gmail_advisory"], EXECUTIVE["outlook"]

    calendar = [
        # Google, the company calendar
        _event(clock, "evt-standup-mon", "google", work, "Leadership stand-up", 0, "09:00", "09:30",
               ["omar", "priya", "jonas"]),
        _event(clock, "evt-nordlicht-qbr", "google", work, "Nordlicht quarterly review", 0, "11:00", "12:00",
               ["greta"], location="Video call"),
        _event(clock, "evt-priya-1on1", "google", work, "1:1 Priya Nair", 0, "15:00", "15:45", ["priya"]),
        _event(clock, "evt-atlas-negotiation", "google", work, "Atlas Pharma contract negotiation", 1,
               "10:00", "11:00", ["daniel", "elena"]),
        _event(clock, "evt-budget-fy27", "google", work, "Budget review FY27", 1, "14:00", "15:00", ["omar"]),
        _event(clock, "evt-pipeline-review", "google", work, "Sales pipeline review", 2, "09:30", "10:30",
               ["jonas"]),
        _event(clock, "evt-bluewater-sync", "google", work, "Bluewater partnership sync", 3, "13:00", "14:00",
               ["ingrid"]),
        _event(clock, "evt-insurance-renewal", "google", work, "Insurance renewal call", 4, "10:00", "10:30",
               ["tomas"]),
        # Google, the advisory account
        _event(clock, "evt-verde-advisory", "google", advisory, "Advisory session: Verde Mobility", 2,
               "16:00", "17:00", ["nora"]),
        # Outlook, the Port Alliance board calendar
        _event(clock, "evt-pa-board", "outlook", board, "Port Alliance board meeting", 1, "16:00", "17:30",
               ["hannah"], organizer="hannah", location="Port Alliance, Room 4"),
        _event(clock, "evt-pa-safety", "outlook", board, "Port Alliance safety committee", 3, "09:00", "10:00",
               ["hannah"]),
    ]

    tasks = [
        {"id": "task-atlas-contract", "title": "Review Atlas Pharma draft contract",
         "due_at": clock.iso(1, "09:00"), "priority": "high", "status": "open"},
        {"id": "task-crane-renewal", "title": "Sign Harbor Crane maintenance renewal",
         "due_at": clock.iso(4, "17:00"), "priority": "medium", "status": "open"},
        {"id": "task-q4-marketing", "title": "Approve Q4 marketing budget",
         "due_at": clock.iso(2, "17:00"), "priority": "medium", "status": "open"},
        {"id": "task-offsite-venue", "title": "Choose venue for leadership offsite",
         "due_at": clock.iso(-3, "17:00"), "priority": "low", "status": "done"},
    ]

    reminders = [
        {"id": "rem-call-omar", "title": "Call Omar before the budget review",
         "remind_at": clock.iso(1, "13:30"), "timezone": TIMEZONE, "status": "scheduled"},
    ]

    # Replies the executive was already waiting for when the day starts.
    follow_ups = [
        {"id": "fu-crane-quote", "subject": "Crane maintenance quote for Q1",
         "threadId": "thread-crane-quote", "waitingOn": {"email": address("karim"), "name": "Karim Saad"},
         "sentAt": clock.iso(-4, "15:10"), "expectedBy": clock.iso(0, "12:00"), "status": "waiting"},
        {"id": "fu-audit-documents", "subject": "Outstanding audit documents",
         "threadId": "thread-audit-documents", "waitingOn": {"email": address("rafael"), "name": "Rafael Costa"},
         "sentAt": clock.iso(-3, "10:05"), "expectedBy": clock.iso(0, "12:00"), "status": "waiting"},
    ]

    # Mail the executive sent before the day starts (the other half of the
    # conversations above).
    sent = [
        {"id": "sent-crane-quote-request", "provider": "gmail", "provider_account_id": work,
         "to": [address("karim")], "subject": "Crane maintenance quote for Q1",
         "text": "Karim, could you send the revised quarterly quote for the two gantry cranes? "
                 "We need it to close the Q1 budget.",
         "thread_id": "thread-crane-quote", "mode": "compose", "in_reply_to": None,
         "sent_at": clock.at(-4, "15:10").astimezone(dt.timezone.utc).isoformat()},
        {"id": "sent-audit-documents-request", "provider": "gmail", "provider_account_id": work,
         "to": [address("rafael")], "subject": "Outstanding audit documents",
         "text": "Rafael, please confirm which documents are still outstanding for the interim audit "
                 "so we can send them this week.",
         "thread_id": "thread-audit-documents", "mode": "compose", "in_reply_to": None,
         "sent_at": clock.at(-3, "10:05").astimezone(dt.timezone.utc).isoformat()},
    ]

    spec: Dict[str, Any] = {
        "version": SPEC_VERSION,
        "seed": int(seed),
        "day": clock.day.isoformat(),
        "timezone": TIMEZONE,
        "worldId": "office-meridian",
        "scribaUser": SCRIBA_USER,
        "organization": ORG,
        "executive": EXECUTIVE,
        "assistantRole": ASSISTANT_ROLE,
        "people": PEOPLE,
        "accounts": {"gmail": [work, advisory], "outlook": board},
        "preferences": PREFERENCES,
        "calendar": calendar,
        "tasks": tasks,
        "reminders": reminders,
        "followUps": follow_ups,
        "sent": sent,
        # Mail present before the day starts is delivered by the day profile
        # (its "backlog"), so each profile states its own morning.
        "startsAt": clock.iso(0, "08:00"),
    }
    spec["fingerprint"] = fingerprint(spec)
    return spec


def fingerprint(value: Any) -> str:
    """A stable digest of any JSON-serialisable value."""
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=True,
                                     default=str).encode("utf-8")).hexdigest()[:16]


def people_by_email(spec: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    return {entry["email"].lower(): entry for entry in spec["people"]}


def own_addresses(spec: Dict[str, Any]) -> List[str]:
    return sorted({spec["scribaUser"], *spec["accounts"]["gmail"], spec["accounts"]["outlook"]})
