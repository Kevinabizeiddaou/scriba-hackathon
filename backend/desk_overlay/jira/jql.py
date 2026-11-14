"""JQL from structured filters, and the named views. Pure.

Every search the Desk runs is built here from typed filters, so a value a
person typed (a project key, a label, a search phrase) is always quoted and
never becomes part of the query's structure. A raw JQL string is accepted
too, for people who write their own: it is passed through after the checks
in ``checked``, and Jira itself applies the caller's permissions to it.

Two rules of Jira Cloud's search (``POST /rest/api/3/search/jql``) shape this
module:

- a query must be BOUNDED: one that restricts nothing is refused, so every
  view carries a restriction and a bare filter set falls back to a window on
  ``updated``;
- results are paged by an opaque token and carry no total, so nothing here
  builds an offset.

The clauses are joined with AND; the only OR is a parenthesized group a named
view adds. That narrow grammar is what lets the sandbox evaluate exactly what
this module emits (``sandbox.py``).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

MAX_JQL_CHARS = 4000
DEFAULT_WINDOW_DAYS = 30
_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,49}$")
_ISSUE_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,49}-[1-9][0-9]{0,9}$")
_ACCOUNT_ID = re.compile(r"^[A-Za-z0-9:_-]{1,128}$")
_NUMBER = re.compile(r"^[0-9]{1,12}$")

# What a result may be ordered by, and the JQL field behind each name.
ORDER_FIELDS: Dict[str, str] = {
    "updated": "updated", "created": "created", "due": "duedate", "priority": "priority",
    "status": "status", "key": "key", "rank": "Rank", "assignee": "assignee",
}
STATUS_CATEGORIES: Dict[str, str] = {"todo": "To Do", "in_progress": "In Progress", "done": "Done"}


class InvalidQuery(ValueError):
    """A filter or a JQL string the Desk will not send. The message is for the person."""


def quote(value: Any) -> str:
    """A JQL string literal. Backslash and the double quote are the only escapes."""
    text = str(value if value is not None else "")
    text = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", " ")
    return f'"{text}"'


def is_issue_key(value: Any) -> bool:
    return bool(_ISSUE_KEY.match(str(value or "").strip()))


def issue_key(value: Any) -> str:
    key = str(value or "").strip().upper()
    if not _ISSUE_KEY.match(key):
        raise InvalidQuery(f"{value!r} is not a Jira issue key (for example DESK-12).")
    return key


def project_key(value: Any) -> str:
    key = str(value or "").strip().upper()
    if not _KEY.match(key):
        raise InvalidQuery(f"{value!r} is not a Jira project key (for example DESK).")
    return key


def _many(values: Any) -> List[str]:
    if values is None:
        return []
    if isinstance(values, str):
        values = values.split(",")
    return [text for text in (str(value).strip() for value in values) if text]


def _in(name: str, values: Sequence[str], render: Any = quote) -> str:
    rendered = [render(value) for value in values]
    return f"{name} = {rendered[0]}" if len(rendered) == 1 else f"{name} in ({', '.join(rendered)})"


def _person(value: str) -> str:
    text = value.strip()
    if text.lower() in ("me", "currentuser()", "currentuser"):
        return "currentUser()"
    if not _ACCOUNT_ID.match(text):
        raise InvalidQuery("A person is named by their Atlassian account id, or as 'me'.")
    return quote(text)


def _days(value: Any, name: str, *, low: int = 0, high: int = 3650) -> int:
    try:
        days = int(value)
    except (TypeError, ValueError):
        raise InvalidQuery(f"{name} is a whole number of days.")
    if not low <= days <= high:
        raise InvalidQuery(f"{name} is between {low} and {high} days.")
    return days


@dataclass(frozen=True)
class Filters:
    """What a person can narrow a search by. Every field is optional."""

    projects: Tuple[str, ...] = ()
    assignee: Optional[str] = None           # "me", "unassigned" or an accountId
    reporter: Optional[str] = None           # "me" or an accountId
    watching: bool = False
    statuses: Tuple[str, ...] = ()
    status_category: Optional[str] = None    # todo | in_progress | done | open (= not done)
    types: Tuple[str, ...] = ()
    priorities: Tuple[str, ...] = ()
    labels: Tuple[str, ...] = ()
    components: Tuple[str, ...] = ()
    fix_versions: Tuple[str, ...] = ()
    sprint: Optional[str] = None             # "open", "future", "closed" or a sprint id
    parent: Optional[str] = None             # an issue key: the epic or the parent task
    text: Optional[str] = None
    updated_within_days: Optional[int] = None
    created_within_days: Optional[int] = None
    due_within_days: Optional[int] = None
    overdue: bool = False
    flagged: bool = False
    extra: Tuple[str, ...] = field(default_factory=tuple)   # clauses a named view adds

    @classmethod
    def from_params(cls, params: Mapping[str, Any]) -> "Filters":
        def text(name: str) -> Optional[str]:
            value = str(params.get(name) or "").strip()
            return value or None

        def number(name: str) -> Optional[int]:
            return None if params.get(name) in (None, "") else _days(params.get(name), name)

        return cls(
            projects=tuple(_many(params.get("project"))), assignee=text("assignee"),
            reporter=text("reporter"), watching=_truthy(params.get("watching")),
            statuses=tuple(_many(params.get("status"))), status_category=text("statusCategory"),
            types=tuple(_many(params.get("type"))), priorities=tuple(_many(params.get("priority"))),
            labels=tuple(_many(params.get("label"))), components=tuple(_many(params.get("component"))),
            fix_versions=tuple(_many(params.get("fixVersion"))), sprint=text("sprint"),
            parent=text("parent"), text=text("text"),
            updated_within_days=number("updatedWithinDays"),
            created_within_days=number("createdWithinDays"),
            due_within_days=number("dueWithinDays"), overdue=_truthy(params.get("overdue")),
            flagged=_truthy(params.get("flagged")),
        )


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def clauses(filters: Filters) -> List[str]:
    out: List[str] = []
    if filters.projects:
        out.append(_in("project", [project_key(key) for key in filters.projects]))
    if filters.assignee:
        out.append("assignee is EMPTY" if filters.assignee.strip().lower() == "unassigned"
                   else f"assignee = {_person(filters.assignee)}")
    if filters.reporter:
        out.append(f"reporter = {_person(filters.reporter)}")
    if filters.watching:
        out.append("watcher = currentUser()")
    if filters.statuses:
        out.append(_in("status", list(filters.statuses)))
    if filters.status_category:
        category = filters.status_category.strip().lower()
        if category == "open":
            out.append("statusCategory != Done")
        elif category in STATUS_CATEGORIES:
            out.append(f"statusCategory = {quote(STATUS_CATEGORIES[category])}")
        else:
            raise InvalidQuery("statusCategory is one of open, todo, in_progress, done.")
    if filters.types:
        out.append(_in("issuetype", list(filters.types)))
    if filters.priorities:
        out.append(_in("priority", list(filters.priorities)))
    if filters.labels:
        out.append(_in("labels", list(filters.labels)))
    if filters.components:
        out.append(_in("component", list(filters.components)))
    if filters.fix_versions:
        out.append(_in("fixVersion", list(filters.fix_versions)))
    if filters.sprint:
        sprint = filters.sprint.strip().lower()
        if sprint in ("open", "future", "closed"):
            out.append(f"sprint in {sprint}Sprints()")
        elif _NUMBER.match(sprint):
            out.append(f"sprint = {sprint}")
        else:
            raise InvalidQuery("sprint is one of open, future, closed, or a sprint id.")
    if filters.parent:
        out.append(f"parent = {issue_key(filters.parent)}")
    if filters.text:
        phrase = filters.text.strip()[:200]
        # Typing an issue key finds that issue: a text search would not.
        out.append(f"key = {issue_key(phrase)}" if is_issue_key(phrase) else f"text ~ {quote(phrase)}")
    if filters.updated_within_days is not None:
        out.append(f"updated >= -{_days(filters.updated_within_days, 'updatedWithinDays')}d")
    if filters.created_within_days is not None:
        out.append(f"created >= -{_days(filters.created_within_days, 'createdWithinDays')}d")
    # A due date is a day, not an instant: an issue due today is not overdue
    # until the day is over, and it is still "due soon" all day.
    if filters.overdue:
        out.append("duedate < startOfDay()")
    if filters.due_within_days is not None:
        out.append(f"duedate <= {_days(filters.due_within_days, 'dueWithinDays')}d")
        if not filters.overdue:
            out.append("duedate >= startOfDay()")
    if filters.flagged:
        out.append("flagged is not EMPTY")
    out.extend(filters.extra)
    return out


def order_by(order: Optional[str], default: str = "updated DESC") -> str:
    """``"due"``, ``"-updated"``, ``"priority,-updated"`` to an ORDER BY clause."""
    parts: List[str] = []
    for item in _many(order):
        descending = item.startswith("-")
        name = item.lstrip("+-").strip().lower()
        if name not in ORDER_FIELDS:
            raise InvalidQuery(f"Results can be ordered by: {', '.join(sorted(ORDER_FIELDS))}.")
        parts.append(f"{ORDER_FIELDS[name]} {'DESC' if descending else 'ASC'}")
    return "ORDER BY " + (", ".join(parts) if parts else default)


def build(filters: Filters, *, order: Optional[str] = None, default_order: str = "updated DESC") -> str:
    """The JQL for a set of filters. Always bounded."""
    parts = clauses(filters)
    if not parts:
        parts = [f"updated >= -{DEFAULT_WINDOW_DAYS}d"]
    return f"{' AND '.join(parts)} {order_by(order, default_order)}"


def checked(raw: Any) -> str:
    """A JQL string a person wrote, fit to send. Jira parses and authorizes it."""
    text = " ".join(str(raw or "").split())
    if not text:
        raise InvalidQuery("The JQL is empty.")
    if len(text) > MAX_JQL_CHARS:
        raise InvalidQuery(f"The JQL is longer than {MAX_JQL_CHARS} characters.")
    if re.match(r"(?i)^order\s+by\b", text):
        raise InvalidQuery("Jira refuses a search that restricts nothing. Add a condition before ORDER BY.")
    return text


# ── named views ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class View:
    id: str
    label: str
    description: str
    filters: Filters
    order: str = "updated DESC"
    # Jira Software (boards and sprints) or Jira Service Management must be on the site.
    needs: Optional[str] = None
    # The JQL is common practice but not in Atlassian's JQL reference: a site
    # may refuse it. The view then says so instead of showing an empty list.
    unverified: bool = False


_OPEN = "open"
VIEWS: Tuple[View, ...] = (
    View("my_open", "Assigned to me", "Open issues assigned to you.",
         Filters(assignee="me", status_category=_OPEN), "priority DESC, updated DESC"),
    View("due_soon", "Due this week", "Your open issues due in the next 7 days.",
         Filters(assignee="me", status_category=_OPEN, due_within_days=7), "duedate ASC"),
    View("overdue", "Overdue", "Your open issues past their due date.",
         Filters(assignee="me", status_category=_OPEN, overdue=True), "duedate ASC"),
    View("my_sprint", "My current sprint", "Your issues in a sprint that is running now.",
         Filters(assignee="me", sprint="open"), "Rank ASC", needs="software"),
    View("reported_by_me", "Reported by me", "Open issues you raised.",
         Filters(reporter="me", status_category=_OPEN)),
    View("watching", "Watching", "Open issues you watch.",
         Filters(watching=True, status_category=_OPEN)),
    View("mentions", "Mentioning me", "Issues updated in the last 14 days whose text or comments mention you.",
         Filters(updated_within_days=14, extra=("text ~ currentUser()",)), unverified=True),
    View("blocked", "Blocked or flagged", "Open issues that are flagged, or in a Blocked status.",
         Filters(status_category=_OPEN, extra=('(flagged is not EMPTY OR status = "Blocked")',)),
         unverified=True),
    View("high_priority", "High priority, open", "Open issues at the two highest priorities.",
         Filters(status_category=_OPEN, priorities=("Highest", "High")), "priority DESC, updated DESC"),
    View("unassigned", "Unassigned", "Open issues nobody owns, updated in the last 30 days.",
         Filters(assignee="unassigned", status_category=_OPEN, updated_within_days=30),
         "priority DESC, created ASC"),
    View("stale", "Stalled in progress", "In progress and untouched for 7 days.",
         Filters(status_category="in_progress", extra=("updated <= -7d",)), "updated ASC"),
    View("recent", "Recently updated", "Everything you can see, updated in the last 7 days.",
         Filters(updated_within_days=7)),
    View("created_recently", "New this week", "Issues created in the last 7 days.",
         Filters(created_within_days=7), "created DESC"),
    View("done_recently", "Done this week", "Issues resolved in the last 7 days.",
         Filters(status_category="done", extra=("resolved >= -7d",)), "resolved DESC"),
    View("my_approvals", "Waiting for my approval", "Service requests that need your approval.",
         Filters(extra=("approvals = myPendingApproval()",)), "created ASC", needs="servicedesk"),
)
VIEW_BY_ID: Dict[str, View] = {view.id: view for view in VIEWS}
DEFAULT_VIEW = "my_open"


def view_jql(view_id: str, extra: Optional[Filters] = None, *, order: Optional[str] = None) -> str:
    """A named view, optionally narrowed further (by project, by text...)."""
    view = VIEW_BY_ID.get(str(view_id or "").strip())
    if view is None:
        raise InvalidQuery(f"There is no view called {view_id!r}.")
    parts = clauses(view.filters)
    if extra is not None:
        parts.extend(clause for clause in clauses(extra) if clause not in parts)
    return f"{' AND '.join(parts)} {order_by(order, view.order)}"


def describe_views() -> List[Dict[str, Any]]:
    return [{"id": view.id, "label": view.label, "description": view.description,
             "needs": view.needs, "unverified": view.unverified, "jql": view_jql(view.id)}
            for view in VIEWS]
