"""The writes the Desk can make to Jira, as a catalogue.

Nothing in the Desk changes Jira by calling the client directly. A write is
one of the actions below, and it goes through four steps, each a function on
the action:

1. ``clean``    the input a person or the assistant gave, checked and
                normalized. Pure: no network. Raises ``InvalidAction``.
2. ``resolve``  what only Jira knows, read at PROPOSAL time and pinned: a
                transition's id and where it leads, an issue's current
                status, a person's display name. The preview is built from
                this, so what is approved is exactly what is shown.
3. ``run``      the write itself, after approval.
4. ``check``    a read-back: did Jira end up in the state the action meant.
                A write Jira accepted but that cannot be confirmed is
                reported as unverified, never as a success.

``guard`` runs just before ``run``: if the issue moved on since the proposal
(somebody else transitioned it), the action is held instead of applied to a
state nobody approved.

Deliberately absent: deleting an issue, deleting someone else's comment, and
any bulk change. The first two destroy other people's work; the third is
approved issue by issue until there is a preview that shows every row.
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from . import adf, jql
from .client import JiraClient, JiraError
from .models import FieldMap, status_view, user_view

MAX_SUMMARY = 255
MAX_ISSUES_PER_MOVE = 50
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DURATION = re.compile(r"(\d+(?:\.\d+)?)\s*(w|d|h|m)", re.IGNORECASE)
# Jira's defaults for time tracking. A site can change them; seconds cannot be misread.
_SECONDS = {"m": 60, "h": 3600, "d": 8 * 3600, "w": 5 * 8 * 3600}


class InvalidAction(ValueError):
    """The input cannot become a proposal. ``problems`` says what to fix."""

    def __init__(self, problems: Sequence[Mapping[str, str]]) -> None:
        self.problems = [dict(problem) for problem in problems]
        super().__init__("; ".join(f"{p.get('field')}: {p.get('message')}" for p in self.problems))


@dataclass
class Context:
    """What an action may use: the client, this site's custom fields, and who is acting."""

    client: JiraClient
    field_map: FieldMap = field(default_factory=FieldMap)
    me: Optional[str] = None                 # the acting person's accountId
    site_url: Optional[str] = None


@dataclass(frozen=True)
class Param:
    name: str
    kind: str            # text | longtext | issue | project | person | date | duration | list | choice | number | bool
    label: str
    required: bool = False
    hint: str = ""


@dataclass(frozen=True)
class Action:
    name: str
    label: str
    description: str
    risk: str                                    # low | medium | high
    needs: str                                   # a scope group in policy.py
    params: Tuple[Param, ...]
    clean: Callable[[Mapping[str, Any]], Dict[str, Any]]
    preview: Callable[[Dict[str, Any]], str]
    run: Callable[[Context, Dict[str, Any]], Dict[str, Any]]
    resolve: Optional[Callable[[Context, Dict[str, Any]], Dict[str, Any]]] = None
    guard: Optional[Callable[[Context, Dict[str, Any]], Optional[str]]] = None
    check: Optional[Callable[[Context, Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = None
    undo: str = ""                               # how a person reverses it, in words

    def targets(self, data: Mapping[str, Any]) -> List[str]:
        keys = [data.get("issue"), data.get("otherIssue"), data.get("parent"), *(data.get("issues") or [])]
        return [str(key) for key in keys if key]

    def describe(self) -> Dict[str, Any]:
        return {"name": self.name, "label": self.label, "description": self.description,
                "risk": self.risk, "needs": self.needs, "undo": self.undo or None,
                "params": [{"name": p.name, "kind": p.kind, "label": p.label,
                            "required": p.required, "hint": p.hint or None} for p in self.params]}


# ── input helpers (pure) ───────────────────────────────────────────────────

class _Reader:
    """Reads fields from the input and collects every problem, so a person
    sees all of them at once instead of one per attempt."""

    def __init__(self, source: Mapping[str, Any]) -> None:
        self.source = source if isinstance(source, Mapping) else {}
        self.problems: List[Dict[str, str]] = []

    def fail(self, name: str, message: str) -> None:
        self.problems.append({"field": name, "message": message})

    def has(self, name: str) -> bool:
        return name in self.source

    def text(self, name: str, *, required: bool = False, limit: int = adf.MAX_TEXT_CHARS,
             one_line: bool = False) -> Optional[str]:
        value = self.source.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            if required:
                self.fail(name, "This is required.")
            return None
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            self.fail(name, "This must be text.")
            return None
        text = str(value).strip()
        if one_line:
            text = " ".join(text.split())
        if len(text) > limit:
            self.fail(name, f"This is longer than {limit} characters.")
            return None
        return text

    def issue(self, name: str, *, required: bool = True) -> Optional[str]:
        value = self.source.get(name)
        if value in (None, ""):
            if required:
                self.fail(name, "An issue key is required (for example DESK-12).")
            return None
        try:
            return jql.issue_key(value)
        except jql.InvalidQuery as exc:
            self.fail(name, str(exc))
            return None

    def issues(self, name: str) -> List[str]:
        raw = self.source.get(name)
        values = raw if isinstance(raw, (list, tuple)) else ([raw] if raw else [])
        keys: List[str] = []
        for value in values:
            try:
                key = jql.issue_key(value)
            except jql.InvalidQuery as exc:
                self.fail(name, str(exc))
                continue
            if key not in keys:
                keys.append(key)
        if not keys and not self.problems:
            self.fail(name, "At least one issue key is required.")
        if len(keys) > MAX_ISSUES_PER_MOVE:
            self.fail(name, f"At most {MAX_ISSUES_PER_MOVE} issues at a time.")
        return keys

    def project(self, name: str = "project") -> Optional[str]:
        try:
            return jql.project_key(self.source.get(name))
        except jql.InvalidQuery as exc:
            self.fail(name, str(exc))
            return None

    def person(self, name: str, *, required: bool = False) -> Optional[str]:
        """An accountId, or ``me``. Never a name or an email: Jira Cloud
        identifies people by accountId only, and a name can match two people."""
        value = self.source.get(name)
        if value in (None, ""):
            if required:
                self.fail(name, "Choose a person.")
            return None
        text = str(value).strip()
        if text.lower() == "me":
            return "me"
        if not re.fullmatch(r"[A-Za-z0-9:_-]{1,128}", text):
            self.fail(name, "Choose a person from the list: Jira identifies people by account id.")
            return None
        return text

    def date(self, name: str) -> Optional[str]:
        value = self.source.get(name)
        if value in (None, ""):
            return None
        text = str(value).strip()[:10]
        try:
            if not _DATE.match(text):
                raise ValueError
            dt.date.fromisoformat(text)
        except ValueError:
            self.fail(name, "A date is written YYYY-MM-DD.")
            return None
        return text

    def names(self, name: str, *, limit: int = 20, no_spaces: bool = False) -> Optional[List[str]]:
        if name not in self.source or self.source.get(name) is None:
            return None
        raw = self.source.get(name)
        values = raw.split(",") if isinstance(raw, str) else list(raw) if isinstance(raw, (list, tuple)) else None
        if values is None:
            self.fail(name, "This must be a list.")
            return None
        out: List[str] = []
        for value in values:
            text = str(value).strip()
            if not text:
                continue
            if no_spaces and re.search(r"\s", text):
                self.fail(name, f"A label cannot contain a space: {text!r}.")
                continue
            if len(text) > 255:
                self.fail(name, "An entry is longer than 255 characters.")
                continue
            if text not in out:
                out.append(text)
        if len(out) > limit:
            self.fail(name, f"At most {limit} entries.")
        return out

    def number(self, name: str, *, low: float = 0, high: float = 100000) -> Optional[float]:
        value = self.source.get(name)
        if value in (None, ""):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            self.fail(name, "This must be a number.")
            return None
        if isinstance(value, bool) or not low <= number <= high:
            self.fail(name, f"This must be between {low:g} and {high:g}.")
            return None
        return number

    def identifier(self, name: str, what: str) -> Optional[int]:
        value = self.source.get(name)
        try:
            number = int(str(value).strip())
            if number <= 0 or isinstance(value, bool):
                raise ValueError
        except (TypeError, ValueError):
            self.fail(name, f"{what} is required.")
            return None
        return number

    def choice(self, name: str, allowed: Sequence[str], *, default: Optional[str] = None) -> Optional[str]:
        value = str(self.source.get(name) or default or "").strip().lower()
        if value not in allowed:
            self.fail(name, f"This must be one of: {', '.join(allowed)}.")
            return None
        return value

    def done(self, data: Dict[str, Any]) -> Dict[str, Any]:
        if self.problems:
            raise InvalidAction(self.problems)
        return data


def parse_duration(value: Any) -> Optional[int]:
    """``"1h 30m"``, ``"2d"``, ``"45m"``, ``"1.5h"`` or a number of seconds, to seconds."""
    if isinstance(value, bool) or value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    text = str(value).strip().lower()
    if re.fullmatch(r"\d+", text):
        return int(text) or None
    matches = _DURATION.findall(text)
    if not matches or _DURATION.sub("", text).strip(" ,"):
        return None
    seconds = sum(float(amount) * _SECONDS[unit.lower()] for amount, unit in matches)
    return int(seconds) if seconds > 0 else None


def format_duration(seconds: Optional[int]) -> str:
    if not seconds:
        return "0m"
    hours, minutes = divmod(int(seconds) // 60, 60)
    return " ".join(part for part in (f"{hours}h" if hours else "", f"{minutes}m" if minutes else "") if part) or "under a minute"


def _person_ref(ctx: Context, value: Optional[str]) -> Optional[str]:
    return ctx.me if value == "me" else value


def _name_of(ctx: Context, account_id: Optional[str], *, issue: Optional[str] = None,
             project: Optional[str] = None) -> Optional[str]:
    """A display name for the preview. Best effort: the id is what is sent."""
    if not account_id:
        return None
    try:
        for user in ctx.client.assignable_users(issue_key=issue, project_key=project, max_results=100):
            if user.get("accountId") == account_id:
                return (user_view(user) or {}).get("displayName")
    except JiraError:
        pass
    return None


def _issue_state(ctx: Context, key: str) -> Dict[str, Any]:
    raw = ctx.client.get_issue(key, fields=["summary", "status", "assignee", "issuetype"])
    fields = raw.get("fields") or {}
    return {"summary": str(fields.get("summary") or "").strip(), "status": status_view(fields.get("status")),
            "assignee": user_view(fields.get("assignee"))}


def _titled(data: Mapping[str, Any], key_field: str = "issue") -> str:
    key = data.get(key_field)
    summary = (data.get("_before") or {}).get("summary")
    return f"{key} ({summary})" if summary else str(key)


# ── create and edit ────────────────────────────────────────────────────────

def _common_fields(reader: _Reader, data: Dict[str, Any]) -> None:
    for name in ("priority",):
        if reader.has(name):
            data[name] = reader.text(name, limit=60, one_line=True)
    if reader.has("assignee"):
        data["assignee"] = reader.person("assignee")
    for name, no_spaces in (("labels", True), ("components", False), ("fixVersions", False)):
        values = reader.names(name, no_spaces=no_spaces)
        if values is not None:
            data[name] = values
    for name in ("dueDate", "startDate"):
        if reader.has(name):
            data[name] = reader.date(name)
    if reader.has("storyPoints"):
        data["storyPoints"] = reader.number("storyPoints", high=1000)
    if reader.has("parent"):
        data["parent"] = reader.issue("parent", required=False)


def _jira_fields(ctx: Context, data: Mapping[str, Any], *, creating: bool) -> Dict[str, Any]:
    """Our field names to Jira's. A key present with None clears the field."""
    fields: Dict[str, Any] = {}
    if "summary" in data:
        fields["summary"] = data["summary"]
    if "description" in data:
        fields["description"] = adf.to_adf(data["description"]) if data["description"] else None
    if "priority" in data:
        fields["priority"] = {"name": data["priority"]} if data["priority"] else None
    if "assignee" in data:
        account_id = _person_ref(ctx, data["assignee"])
        fields["assignee"] = {"accountId": account_id} if account_id else None
    if "labels" in data:
        fields["labels"] = list(data["labels"])
    if "components" in data:
        fields["components"] = [{"name": name} for name in data["components"]]
    if "fixVersions" in data:
        fields["fixVersions"] = [{"name": name} for name in data["fixVersions"]]
    if "dueDate" in data:
        fields["duedate"] = data["dueDate"]
    if "parent" in data:
        fields["parent"] = {"key": data["parent"]} if data["parent"] else None
    if "startDate" in data and ctx.field_map.start_date:
        fields[ctx.field_map.start_date] = data["startDate"]
    if "storyPoints" in data and ctx.field_map.story_points:
        fields[data.get("_pointsField") or ctx.field_map.story_points[0]] = data["storyPoints"]
    if creating:
        # On create a field that is absent takes the project's default: an
        # explicit null is refused for most of them.
        fields = {key: value for key, value in fields.items() if value is not None}
    return fields


def _clean_create(source: Mapping[str, Any]) -> Dict[str, Any]:
    reader = _Reader(source)
    data: Dict[str, Any] = {
        "project": reader.project(),
        "issueType": reader.text("issueType", limit=60, one_line=True) or "Task",
        "summary": reader.text("summary", required=True, limit=MAX_SUMMARY, one_line=True),
    }
    description = reader.text("description")
    if description:
        data["description"] = description
    _common_fields(reader, data)
    if reader.has("sprint") and source.get("sprint") not in (None, ""):
        data["sprint"] = reader.identifier("sprint", "A sprint")
    return reader.done({key: value for key, value in data.items() if value is not None})


def _resolve_create(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    """Pin the issue type by id and say now, not after approval, what the
    project requires that was not given."""
    types = (ctx.client.create_meta_types(data["project"]).get("issueTypes") or [])
    wanted = data["issueType"].strip().lower()
    match = next((kind for kind in types if str(kind.get("name") or "").lower() == wanted), None)
    if match is None:
        names = ", ".join(sorted(str(kind.get("name")) for kind in types if kind.get("name")))
        raise InvalidAction([{"field": "issueType",
                              "message": f"{data['project']} has no issue type called {data['issueType']!r}. "
                                         f"It has: {names or 'none you can create'}."}])
    data["_issueTypeId"] = str(match.get("id"))
    data["issueType"] = str(match.get("name"))
    if match.get("subtask") and not data.get("parent"):
        raise InvalidAction([{"field": "parent", "message": "A sub-task needs the issue it belongs to."}])
    meta = ctx.client.create_meta_fields(data["project"], match.get("id")).get("fields") or []
    ours = {"project", "issuetype", "summary", "description", "priority", "assignee", "labels", "components",
            "fixVersions", "duedate", "parent", "reporter"}
    missing = [str(row.get("name") or row.get("fieldId")) for row in meta
               if row.get("required") and not row.get("hasDefaultValue")
               and str(row.get("fieldId") or row.get("key")) not in ours]
    if missing:
        raise InvalidAction([{"field": "issueType",
                              "message": f"{data['project']} requires fields the Desk cannot fill yet for "
                                         f"{data['issueType']}: {', '.join(missing)}. Create it in Jira."}])
    if data.get("assignee"):
        data["_assigneeName"] = _name_of(ctx, _person_ref(ctx, data["assignee"]), project=data["project"])
    return data


def _preview_create(data: Dict[str, Any]) -> str:
    extras = []
    if data.get("parent"):
        extras.append(f"under {data['parent']}")
    if data.get("assignee"):
        extras.append(f"assigned to {data.get('_assigneeName') or ('you' if data['assignee'] == 'me' else 'the chosen person')}")
    if data.get("priority"):
        extras.append(f"priority {data['priority']}")
    if data.get("dueDate"):
        extras.append(f"due {data['dueDate']}")
    tail = f" ({', '.join(extras)})" if extras else ""
    return f"Create a {data['issueType']} in {data['project']}: '{data['summary']}'{tail}."


def _run_create(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    fields = _jira_fields(ctx, data, creating=True)
    fields["project"] = {"key": data["project"]}
    fields["issuetype"] = {"id": data["_issueTypeId"]} if data.get("_issueTypeId") else {"name": data["issueType"]}
    created = ctx.client.create_issue(fields)
    key = str(created.get("key") or "")
    if key and data.get("sprint"):
        ctx.client.move_to_sprint(data["sprint"], [key])
    return {"issueKey": key, "issueId": created.get("id")}


def _check_create(ctx: Context, data: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    key = result.get("issueKey")
    if not key:
        return {"verified": False, "detail": "Jira did not return the new issue's key."}
    state = _issue_state(ctx, key)
    same = state["summary"] == data["summary"]
    return {"verified": same, "detail": f"{key} exists with the summary that was approved." if same
            else f"{key} exists but its summary differs from what was approved."}


def _clean_edit(source: Mapping[str, Any]) -> Dict[str, Any]:
    reader = _Reader(source)
    data: Dict[str, Any] = {"issue": reader.issue("issue")}
    if reader.has("summary"):
        data["summary"] = reader.text("summary", required=True, limit=MAX_SUMMARY, one_line=True)
    if reader.has("description"):
        data["description"] = reader.text("description") or ""
    _common_fields(reader, data)
    for name in ("addLabels", "removeLabels"):
        values = reader.names(name, no_spaces=True)
        if values:
            data[name] = values
    data["notify"] = source.get("notify") is not False
    if len([key for key in data if key not in ("issue", "notify")]) == 0 and not reader.problems:
        reader.fail("issue", "Nothing to change was given.")
    return reader.done(data)


def _resolve_edit(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    data["_before"] = _issue_state(ctx, data["issue"])
    editable = (ctx.client.edit_meta(data["issue"]).get("fields") or {})
    if "storyPoints" in data:
        field_id = next((fid for fid in ctx.field_map.story_points if fid in editable), None)
        if field_id is None:
            raise InvalidAction([{"field": "storyPoints",
                                  "message": "This issue has no story points field you can edit."}])
        data["_pointsField"] = field_id
    names = {"summary": "summary", "description": "description", "priority": "priority",
             "labels": "labels", "addLabels": "labels", "removeLabels": "labels", "components": "components",
             "fixVersions": "fixVersions", "dueDate": "duedate", "parent": "parent", "assignee": "assignee"}
    locked = sorted({ours for ours, theirs in names.items() if ours in data and theirs not in editable})
    if locked:
        raise InvalidAction([{"field": name, "message": "This field cannot be edited on this issue "
                              "(it is not on the edit screen, or you lack permission)."} for name in locked])
    if data.get("assignee"):
        data["_assigneeName"] = _name_of(ctx, _person_ref(ctx, data["assignee"]), issue=data["issue"])
    return data


_EDIT_WORDS = {"summary": "summary", "description": "description", "priority": "priority", "labels": "labels",
               "addLabels": "labels", "removeLabels": "labels", "components": "components",
               "fixVersions": "fix versions", "dueDate": "due date", "startDate": "start date",
               "storyPoints": "story points", "parent": "parent", "assignee": "assignee"}


def _preview_edit(data: Dict[str, Any]) -> str:
    changes: List[str] = []
    for name, word in _EDIT_WORDS.items():
        if name not in data:
            continue
        value = data[name]
        if name == "description":
            changes.append("replace the description" if value else "clear the description")
        elif name == "addLabels":
            changes.append(f"add label{'s' if len(value) != 1 else ''} {', '.join(value)}")
        elif name == "removeLabels":
            changes.append(f"remove label{'s' if len(value) != 1 else ''} {', '.join(value)}")
        elif name == "assignee":
            changes.append(f"assign to {data.get('_assigneeName') or ('you' if value == 'me' else 'the chosen person')}"
                           if value else "unassign")
        elif value in (None, "", []):
            changes.append(f"clear the {word}")
        elif isinstance(value, list):
            changes.append(f"set {word} to {', '.join(value)}")
        else:
            changes.append(f"set {word} to '{value}'" if name == "summary" else f"set {word} to {value:g}"
                           if isinstance(value, float) else f"set {word} to {value}")
    quiet = "" if data.get("notify", True) else " Watchers are not notified."
    return f"Edit {_titled(data)}: {'; '.join(changes)}.{quiet}"


def _run_edit(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    fields = _jira_fields(ctx, data, creating=False)
    update: Dict[str, Any] = {}
    label_ops = [{"add": label} for label in data.get("addLabels") or []] + \
                [{"remove": label} for label in data.get("removeLabels") or []]
    if label_ops:
        update["labels"] = label_ops
        fields.pop("labels", None)
    ctx.client.edit_issue(data["issue"], fields=fields or None, update=update or None,
                          notify=bool(data.get("notify", True)))
    return {"issueKey": data["issue"]}


def _check_edit(ctx: Context, data: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    wanted = [name for name in ("summary", "duedate", "priority", "labels") if name in _jira_fields(ctx, data, creating=False)]
    if not wanted:
        return {"verified": None, "detail": "Jira accepted the change. It was not read back."}
    fields = ctx.client.get_issue(data["issue"], fields=wanted).get("fields") or {}
    problems: List[str] = []
    if "summary" in data and str(fields.get("summary") or "").strip() != data["summary"]:
        problems.append("summary")
    if "dueDate" in data and (fields.get("duedate") or None) != (data["dueDate"] or None):
        problems.append("due date")
    if "priority" in data and data["priority"] and \
            str((fields.get("priority") or {}).get("name") or "").lower() != data["priority"].lower():
        problems.append("priority")
    if "labels" in data and sorted(fields.get("labels") or []) != sorted(data["labels"]):
        problems.append("labels")
    return {"verified": not problems,
            "detail": "The issue now reads as approved." if not problems
            else f"Jira accepted the change but these read back differently: {', '.join(problems)}."}


# ── transition, assign, comment ────────────────────────────────────────────

def _clean_transition(source: Mapping[str, Any]) -> Dict[str, Any]:
    reader = _Reader(source)
    data: Dict[str, Any] = {"issue": reader.issue("issue"),
                            "transition": reader.text("transition", required=True, limit=120, one_line=True)}
    for name in ("resolution", "comment"):
        value = reader.text(name, limit=120 if name == "resolution" else adf.MAX_TEXT_CHARS)
        if value:
            data[name] = value
    return reader.done(data)


def match_transition(transitions: Sequence[Mapping[str, Any]],
                     wanted: str) -> Tuple[Optional[Mapping[str, Any]], List[str], bool]:
    """The one transition a person meant: by id, by exact name, by the status
    it leads to, then by a unique partial match. Returns the transition, the
    names to offer when there is none, and whether that is because more than
    one matched. Two candidates is not a match: the person chooses."""
    text = wanted.strip().lower()
    for test in (
        lambda item: str(item.get("id")) == wanted.strip(),
        lambda item: str(item.get("name") or "").lower() == text,
        lambda item: str((item.get("to") or {}).get("name") or "").lower() == text,
        lambda item: text in str(item.get("name") or "").lower()
        or text in str((item.get("to") or {}).get("name") or "").lower(),
    ):
        found = [item for item in transitions if test(item)]
        if len(found) == 1:
            return found[0], [], False
        if len(found) > 1:
            return None, [str(item.get("name") or "") for item in found], True
    return None, [str(item.get("name") or "") for item in transitions], False


def _resolve_transition(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    data["_before"] = _issue_state(ctx, data["issue"])
    transitions = ctx.client.transitions(data["issue"]).get("transitions") or []
    chosen, names, ambiguous = match_transition(transitions, data["transition"])
    if chosen is None:
        listed = ", ".join(name for name in names if name) or "none"
        message = (f"More than one move matches {data['transition']!r}: {listed}. Say which." if ambiguous
                   else f"{data['issue']} cannot make that move from {data['_before']['status']['name']}. "
                        f"Available: {listed}.")
        raise InvalidAction([{"field": "transition", "message": message}])
    data["_transitionId"] = str(chosen.get("id"))
    data["transition"] = str(chosen.get("name") or data["transition"])
    data["_to"] = status_view(chosen.get("to"))
    required = [str(spec.get("name") or field_id) for field_id, spec in (chosen.get("fields") or {}).items()
                if isinstance(spec, Mapping) and spec.get("required") and not spec.get("hasDefaultValue")
                and not (field_id == "resolution" and data.get("resolution"))]
    if required:
        raise InvalidAction([{"field": "transition",
                              "message": f"This move asks for: {', '.join(required)}. "
                                         + ("Give a resolution. " if "Resolution" in required else "")
                                         + "The Desk can fill a resolution and a comment; make other moves in Jira."}])
    if data.get("resolution") and "resolution" not in (chosen.get("fields") or {}):
        data.pop("resolution")                       # this move has no resolution to set
    return data


def _preview_transition(data: Dict[str, Any]) -> str:
    before = ((data.get("_before") or {}).get("status") or {}).get("name")
    to = (data.get("_to") or {}).get("name") or data["transition"]
    move = f"from {before} to {to}" if before else f"to {to}"
    extras = [f"resolution {data['resolution']}" if data.get("resolution") else "",
              "with a comment" if data.get("comment") else ""]
    tail = f" ({', '.join(extra for extra in extras if extra)})" if any(extras) else ""
    return f"Move {_titled(data)} {move}{tail}."


def _guard_transition(ctx: Context, data: Dict[str, Any]) -> Optional[str]:
    before = ((data.get("_before") or {}).get("status") or {}).get("name")
    now = _issue_state(ctx, data["issue"])["status"]["name"]
    if before and now != before:
        return (f"{data['issue']} was {before} when this was proposed and is {now} now, so the move "
                "was not made. Propose it again from the current status.")
    return None


def _run_transition(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    fields = {"resolution": {"name": data["resolution"]}} if data.get("resolution") else None
    update = {"comment": [{"add": {"body": adf.to_adf(data["comment"])}}]} if data.get("comment") else None
    ctx.client.transition(data["issue"], data["_transitionId"], fields=fields, update=update)
    return {"issueKey": data["issue"], "to": (data.get("_to") or {}).get("name")}


def _check_transition(ctx: Context, data: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    wanted = (data.get("_to") or {}).get("name")
    now = _issue_state(ctx, data["issue"])["status"]["name"]
    return {"verified": bool(wanted) and now == wanted,
            "detail": f"{data['issue']} is now {now}." if now == wanted
            else f"{data['issue']} is {now}, not {wanted}."}


def _clean_assign(source: Mapping[str, Any]) -> Dict[str, Any]:
    reader = _Reader(source)
    data = {"issue": reader.issue("issue"), "assignee": reader.person("assignee")}
    return reader.done(data)


def _resolve_assign(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    data["_before"] = _issue_state(ctx, data["issue"])
    account_id = _person_ref(ctx, data["assignee"])
    if account_id:
        name = _name_of(ctx, account_id, issue=data["issue"])
        if name is None:
            raise InvalidAction([{"field": "assignee",
                                  "message": f"That person cannot be assigned {data['issue']}."}])
        data["_assigneeName"] = name
    return data


def _preview_assign(data: Dict[str, Any]) -> str:
    current = ((data.get("_before") or {}).get("assignee") or {}).get("displayName")
    was = f" (now {current})" if current else " (now unassigned)" if data.get("_before") else ""
    if not data.get("assignee"):
        return f"Unassign {_titled(data)}{was}."
    return f"Assign {_titled(data)} to {data.get('_assigneeName') or 'you'}{was}."


def _run_assign(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    ctx.client.assign(data["issue"], _person_ref(ctx, data["assignee"]))
    return {"issueKey": data["issue"]}


def _check_assign(ctx: Context, data: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    now = (_issue_state(ctx, data["issue"])["assignee"] or {}).get("accountId")
    wanted = _person_ref(ctx, data["assignee"])
    return {"verified": now == wanted,
            "detail": "The assignee reads back as approved." if now == wanted
            else "Jira accepted the change but the assignee reads back differently."}


def _clean_comment(source: Mapping[str, Any]) -> Dict[str, Any]:
    reader = _Reader(source)
    data: Dict[str, Any] = {"issue": reader.issue("issue"), "body": reader.text("body", required=True)}
    if source.get("internal") is True:
        data["internal"] = True                      # a service request's internal note
    return reader.done(data)


def _resolve_comment(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    data["_before"] = _issue_state(ctx, data["issue"])
    mentioned = adf.mentioned_account_ids(adf.to_adf(data["body"]))
    if mentioned:
        people = ctx.client.mentionable_users("", issue_key=data["issue"], max_results=100)
        names = {user.get("accountId"): user.get("displayName") for user in people}
        data["_mentions"] = {account_id: names.get(account_id) for account_id in mentioned}
    return data


def _preview_comment(data: Dict[str, Any]) -> str:
    mentions = [name or "someone who may not see this issue" for name in (data.get("_mentions") or {}).values()]
    note = f" It notifies {', '.join(mentions)}." if mentions else ""
    kind = "an internal note" if data.get("internal") else "a comment"
    names = {account_id: name for account_id, name in (data.get("_mentions") or {}).items() if name}
    text = adf.excerpt(adf.to_adf(data["body"], mention_names=names), 160)
    return f"Add {kind} to {_titled(data)}: '{text}'.{note}"


def _run_comment(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    names = {account_id: name for account_id, name in (data.get("_mentions") or {}).items() if name}
    body = adf.to_adf(data["body"], mention_names=names)
    # A service request's comment is public to the customer unless this property says otherwise.
    properties = [{"key": "sd.public.comment", "value": {"internal": True}}] if data.get("internal") else None
    created = ctx.client.add_comment(data["issue"], body, properties=properties)
    return {"issueKey": data["issue"], "commentId": created.get("id")}


def _check_made(what: str, id_field: str) -> Callable[[Context, Dict[str, Any], Dict[str, Any]], Dict[str, Any]]:
    def check(ctx: Context, data: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        made = bool(result.get(id_field))
        return {"verified": made, "detail": f"Jira returned the new {what}'s id." if made
                else f"Jira accepted the request but returned no {what} id."}
    return check


# ── time, links, watching ──────────────────────────────────────────────────

def _clean_worklog(source: Mapping[str, Any]) -> Dict[str, Any]:
    reader = _Reader(source)
    data: Dict[str, Any] = {"issue": reader.issue("issue")}
    seconds = parse_duration(source.get("timeSpent"))
    if seconds is None:
        reader.fail("timeSpent", "Time is written like 1h 30m, 45m or 2d.")
    elif seconds > 7 * 24 * 3600:
        reader.fail("timeSpent", "A single worklog is at most a week.")
    else:
        data["seconds"] = seconds
    started = reader.date("started")
    if started:
        data["started"] = started
    comment = reader.text("comment", limit=2000)
    if comment:
        data["comment"] = comment
    return reader.done(data)


def _run_worklog(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    started = f"{data['started']}T09:00:00.000+0000" if data.get("started") else None
    created = ctx.client.add_worklog(data["issue"], seconds=data["seconds"], started=started,
                                     comment=adf.to_adf(data["comment"]) if data.get("comment") else None)
    return {"issueKey": data["issue"], "worklogId": created.get("id")}


def _clean_link(source: Mapping[str, Any]) -> Dict[str, Any]:
    reader = _Reader(source)
    data: Dict[str, Any] = {
        "issue": reader.issue("issue"), "otherIssue": reader.issue("otherIssue"),
        "linkType": reader.text("linkType", limit=60, one_line=True) or "Relates",
        "direction": reader.choice("direction", ("outward", "inward"), default="outward"),
    }
    if data["issue"] and data["issue"] == data["otherIssue"]:
        reader.fail("otherIssue", "An issue cannot be linked to itself.")
    return reader.done(data)


def _resolve_link(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    data["_before"] = _issue_state(ctx, data["issue"])
    data["_other"] = _issue_state(ctx, data["otherIssue"])
    types = ctx.client.link_types().get("issueLinkTypes") or []
    wanted = data["linkType"].strip().lower()
    for kind in types:
        phrases = {str(kind.get(part) or "").lower() for part in ("name", "inward", "outward")}
        if wanted in phrases:
            # "is blocked by" names the direction as well as the type.
            if wanted == str(kind.get("inward") or "").lower() != str(kind.get("outward") or "").lower():
                data["direction"] = "inward"
            data["linkType"] = str(kind.get("name"))
            data["_phrase"] = str(kind.get(data["direction"]) or kind.get("name"))
            return data
    names = ", ".join(sorted(str(kind.get("name")) for kind in types if kind.get("name")))
    raise InvalidAction([{"field": "linkType", "message": f"This site has no link type {data['linkType']!r}. "
                                                         f"It has: {names or 'none'}."}])


def _run_link(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    outward, inward = (data["issue"], data["otherIssue"]) if data["direction"] == "outward" \
        else (data["otherIssue"], data["issue"])
    ctx.client.link_issues(type_name=data["linkType"], inward_key=inward, outward_key=outward)
    return {"issueKey": data["issue"], "otherIssue": data["otherIssue"]}


def _clean_issue_only(source: Mapping[str, Any]) -> Dict[str, Any]:
    reader = _Reader(source)
    return reader.done({"issue": reader.issue("issue")})


def _resolve_before(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    data["_before"] = _issue_state(ctx, data["issue"])
    return data


def _run_watch(watching: bool) -> Callable[[Context, Dict[str, Any]], Dict[str, Any]]:
    def run(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
        if not ctx.me:
            raise JiraError(409, "identity_unknown", "The Desk could not tell which Jira account is yours.")
        (ctx.client.add_watcher if watching else ctx.client.remove_watcher)(data["issue"], ctx.me)
        return {"issueKey": data["issue"], "watching": watching}
    return run


# ── sprints, backlog, releases (Jira Software) ─────────────────────────────

def _clean_move_sprint(source: Mapping[str, Any]) -> Dict[str, Any]:
    reader = _Reader(source)
    return reader.done({"sprint": reader.identifier("sprint", "A sprint"), "issues": reader.issues("issues")})


def _resolve_sprint(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    sprint = ctx.client.sprint(data["sprint"])
    data["_sprint"] = {"name": sprint.get("name"), "state": str(sprint.get("state") or "").lower()}
    if data["_sprint"]["state"] == "closed" and "issues" in data:
        raise InvalidAction([{"field": "sprint", "message": f"{sprint.get('name')} is closed."}])
    return data


def _clean_backlog(source: Mapping[str, Any]) -> Dict[str, Any]:
    reader = _Reader(source)
    return reader.done({"issues": reader.issues("issues")})


def _clean_rank(source: Mapping[str, Any]) -> Dict[str, Any]:
    reader = _Reader(source)
    data: Dict[str, Any] = {"issues": reader.issues("issues")}
    before, after = reader.issue("before", required=False), reader.issue("after", required=False)
    if bool(before) == bool(after):
        reader.fail("before", "Say which issue to rank these before, or which to rank them after.")
    data.update({"before": before} if before else {"after": after})
    return reader.done(data)


def _clean_create_sprint(source: Mapping[str, Any]) -> Dict[str, Any]:
    reader = _Reader(source)
    data: Dict[str, Any] = {"board": reader.identifier("board", "A board"),
                            "name": reader.text("name", required=True, limit=30, one_line=True)}
    goal = reader.text("goal", limit=1000)
    if goal:
        data["goal"] = goal
    for name in ("startDate", "endDate"):
        value = reader.date(name)
        if value:
            data[name] = value
    if data.get("startDate") and data.get("endDate") and data["endDate"] <= data["startDate"]:
        reader.fail("endDate", "A sprint ends after it starts.")
    return reader.done(data)


def _clean_sprint_only(source: Mapping[str, Any]) -> Dict[str, Any]:
    reader = _Reader(source)
    return reader.done({"sprint": reader.identifier("sprint", "A sprint")})


def _clean_start_sprint(source: Mapping[str, Any]) -> Dict[str, Any]:
    reader = _Reader(source)
    data: Dict[str, Any] = {"sprint": reader.identifier("sprint", "A sprint"),
                            "startDate": reader.date("startDate"), "endDate": reader.date("endDate")}
    if not data["endDate"]:
        reader.fail("endDate", "A sprint needs an end date to start.")
    return reader.done({key: value for key, value in data.items() if value is not None})


def _resolve_start_sprint(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    data = _resolve_sprint(ctx, data)
    if data["_sprint"]["state"] != "future":
        raise InvalidAction([{"field": "sprint",
                              "message": f"{data['_sprint']['name']} is {data['_sprint']['state']}; only a sprint "
                                         "that has not started can be started."}])
    return data


def _run_start_sprint(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    ctx.client.update_sprint(data["sprint"], {
        "state": "active", "startDate": f"{data.get('startDate') or today}T09:00:00.000Z",
        "endDate": f"{data['endDate']}T17:00:00.000Z"})
    return {"sprintId": data["sprint"], "state": "active"}


def _resolve_complete_sprint(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    data = _resolve_sprint(ctx, data)
    if data["_sprint"]["state"] != "active":
        raise InvalidAction([{"field": "sprint",
                              "message": f"{data['_sprint']['name']} is not running, so it cannot be completed."}])
    page = ctx.client.sprint_issues(data["sprint"], fields=["status"], max_results=100)
    open_keys = [issue.get("key") for issue in (page.get("issues") or [])
                 if status_view((issue.get("fields") or {}).get("status"))["category"] != "done"]
    data["_openCount"] = len(open_keys)
    data["_openSample"] = open_keys[:5]
    return data


def _preview_complete_sprint(data: Dict[str, Any]) -> str:
    left = data.get("_openCount") or 0
    note = (f" {left} unfinished issue{'s' if left != 1 else ''} will move to the backlog"
            f" ({', '.join(data.get('_openSample') or [])}{'…' if left > 5 else ''}).") if left else " Every issue in it is done."
    return f"Complete the sprint {(data.get('_sprint') or {}).get('name') or data['sprint']}.{note}"


def _check_sprint_state(wanted: str) -> Callable[[Context, Dict[str, Any], Dict[str, Any]], Dict[str, Any]]:
    def check(ctx: Context, data: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        state = str(ctx.client.sprint(data["sprint"]).get("state") or "").lower()
        return {"verified": state == wanted, "detail": f"The sprint is now {state}."}
    return check


def _clean_create_version(source: Mapping[str, Any]) -> Dict[str, Any]:
    reader = _Reader(source)
    data: Dict[str, Any] = {"project": reader.project(),
                            "name": reader.text("name", required=True, limit=255, one_line=True)}
    description = reader.text("description", limit=16000)
    if description:
        data["description"] = description
    for name in ("startDate", "releaseDate"):
        value = reader.date(name)
        if value:
            data[name] = value
    return reader.done(data)


def _run_create_version(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    project = ctx.client.get_project(data["project"])
    created = ctx.client.create_version(project_id=project.get("id"), name=data["name"],
                                        description=data.get("description"),
                                        start_date=data.get("startDate"), release_date=data.get("releaseDate"))
    return {"versionId": created.get("id"), "project": data["project"]}


def _clean_release_version(source: Mapping[str, Any]) -> Dict[str, Any]:
    reader = _Reader(source)
    data: Dict[str, Any] = {"version": reader.identifier("version", "A version"),
                            "releaseDate": reader.date("releaseDate")}
    return reader.done({key: value for key, value in data.items() if value is not None})


def _resolve_release_version(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    version = ctx.client.version(data["version"])
    if version.get("released"):
        raise InvalidAction([{"field": "version", "message": f"{version.get('name')} is already released."}])
    data["_name"] = str(version.get("name") or data["version"])
    unresolved = ctx.client.version_unresolved_count(data["version"])
    data["_open"] = int(unresolved.get("issuesUnresolvedCount") or 0)
    data["_total"] = int(unresolved.get("issuesCount") or 0)
    return data


def _run_release_version(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    ctx.client.update_version(data["version"], {"released": True, "releaseDate": data.get("releaseDate") or today})
    return {"versionId": data["version"], "released": True}


def _check_release_version(ctx: Context, data: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    released = bool(ctx.client.version(data["version"]).get("released"))
    return {"verified": released, "detail": "The version reads back as released." if released
            else "Jira accepted the change but the version does not read back as released."}


# ── Jira Service Management ────────────────────────────────────────────────

def _clean_approval(source: Mapping[str, Any]) -> Dict[str, Any]:
    reader = _Reader(source)
    return reader.done({"issue": reader.issue("issue"),
                        "approval": reader.identifier("approval", "An approval"),
                        "decision": reader.choice("decision", ("approve", "decline"))})


def _run_approval(ctx: Context, data: Dict[str, Any]) -> Dict[str, Any]:
    answered = ctx.client.answer_approval(data["issue"], data["approval"], data["decision"])
    return {"issueKey": data["issue"], "decision": answered.get("finalDecision") or data["decision"]}


def _plural(keys: Sequence[str]) -> str:
    shown = ", ".join(keys[:6]) + ("…" if len(keys) > 6 else "")
    return f"{len(keys)} issue{'s' if len(keys) != 1 else ''} ({shown})"


_ISSUE = Param("issue", "issue", "Issue", True)
_OPTIONAL_FIELDS = (
    Param("priority", "choice", "Priority"), Param("assignee", "person", "Assignee"),
    Param("labels", "list", "Labels"), Param("components", "list", "Components"),
    Param("fixVersions", "list", "Fix versions"), Param("dueDate", "date", "Due date"),
    Param("startDate", "date", "Start date"), Param("storyPoints", "number", "Story points"),
    Param("parent", "issue", "Parent", hint="The epic, or the issue a sub-task belongs to."),
)

ACTIONS: Tuple[Action, ...] = (
    Action("create_issue", "Create an issue", "A new issue in a project.", "medium", "core_write",
           (Param("project", "project", "Project", True), Param("issueType", "choice", "Type", hint="Default Task."),
            Param("summary", "text", "Summary", True), Param("description", "longtext", "Description"),
            *_OPTIONAL_FIELDS, Param("sprint", "number", "Sprint")),
           _clean_create, _preview_create, _run_create, resolve=_resolve_create, check=_check_create,
           undo="Delete or close the issue in Jira."),
    Action("edit_issue", "Edit an issue", "Change fields of an issue.", "medium", "core_write",
           (_ISSUE, Param("summary", "text", "Summary"), Param("description", "longtext", "Description"),
            *_OPTIONAL_FIELDS, Param("addLabels", "list", "Add labels"),
            Param("removeLabels", "list", "Remove labels"),
            Param("notify", "bool", "Notify watchers", hint="Default yes.")),
           _clean_edit, _preview_edit, _run_edit, resolve=_resolve_edit, check=_check_edit,
           undo="Jira keeps the previous values in the issue's history."),
    Action("transition_issue", "Move an issue", "Move an issue along its workflow.", "medium", "core_write",
           (_ISSUE, Param("transition", "choice", "Move to", True, "A transition or the status it leads to."),
            Param("resolution", "choice", "Resolution"), Param("comment", "longtext", "Comment")),
           _clean_transition, _preview_transition, _run_transition, resolve=_resolve_transition,
           guard=_guard_transition, check=_check_transition,
           undo="Move it back, if the workflow has a transition for that."),
    Action("assign_issue", "Assign an issue", "Set or clear the assignee.", "medium", "core_write",
           (_ISSUE, Param("assignee", "person", "Assignee", hint="Empty unassigns.")),
           _clean_assign, _preview_assign, _run_assign, resolve=_resolve_assign, check=_check_assign,
           undo="Assign it back."),
    Action("add_comment", "Comment", "Add a comment. Mentions notify people.", "low", "core_write",
           (_ISSUE, Param("body", "longtext", "Comment", True, "Mention with [~accountid:<id>]."),
            Param("internal", "bool", "Internal note", hint="Service requests only.")),
           _clean_comment, _preview_comment, _run_comment, resolve=_resolve_comment,
           check=_check_made("comment", "commentId"), undo="Delete the comment in Jira."),
    Action("log_work", "Log time", "Record time spent on an issue.", "low", "core_write",
           (_ISSUE, Param("timeSpent", "duration", "Time spent", True, "1h 30m, 45m, 2d."),
            Param("started", "date", "On"), Param("comment", "longtext", "What was done")),
           _clean_worklog,
           lambda data: f"Log {format_duration(data['seconds'])} on {data['issue']}"
                        f"{' for ' + data['started'] if data.get('started') else ''}.",
           _run_worklog, check=_check_made("worklog", "worklogId"), undo="Delete the worklog in Jira."),
    Action("link_issues", "Link two issues", "Relate, block or duplicate.", "low", "core_write",
           (_ISSUE, Param("linkType", "choice", "Link", hint="Blocks, Relates, Duplicate…"),
            Param("otherIssue", "issue", "Other issue", True),
            Param("direction", "choice", "Direction", hint="outward: this issue blocks the other.")),
           _clean_link,
           lambda data: f"Link {data['issue']} {data.get('_phrase') or data['linkType'].lower()} {data['otherIssue']}.",
           _run_link, resolve=_resolve_link, undo="Remove the link in Jira."),
    Action("watch_issue", "Watch an issue", "Get its notifications.", "low", "core_write", (_ISSUE,),
           _clean_issue_only, lambda data: f"Start watching {_titled(data)}.", _run_watch(True),
           resolve=_resolve_before, undo="Stop watching."),
    Action("unwatch_issue", "Stop watching", "Stop its notifications.", "low", "core_write", (_ISSUE,),
           _clean_issue_only, lambda data: f"Stop watching {_titled(data)}.", _run_watch(False),
           resolve=_resolve_before, undo="Watch it again."),
    Action("move_to_sprint", "Move to a sprint", "Put issues in a sprint.", "medium", "software_write",
           (Param("sprint", "number", "Sprint", True), Param("issues", "list", "Issues", True)),
           _clean_move_sprint,
           lambda data: f"Move {_plural(data['issues'])} into {(data.get('_sprint') or {}).get('name') or 'sprint ' + str(data['sprint'])}.",
           lambda ctx, data: (ctx.client.move_to_sprint(data["sprint"], data["issues"]),
                              {"sprintId": data["sprint"], "issues": data["issues"]})[1],
           resolve=_resolve_sprint, undo="Move them back to the backlog or their previous sprint."),
    Action("move_to_backlog", "Move to the backlog", "Take issues out of their sprint.", "medium", "software_write",
           (Param("issues", "list", "Issues", True),), _clean_backlog,
           lambda data: f"Move {_plural(data['issues'])} to the backlog.",
           lambda ctx, data: (ctx.client.move_to_backlog(data["issues"]), {"issues": data["issues"]})[1],
           undo="Move them back into the sprint."),
    Action("rank_issues", "Reorder issues", "Rank issues before or after another.", "low", "software_write",
           (Param("issues", "list", "Issues", True), Param("before", "issue", "Before"),
            Param("after", "issue", "After")), _clean_rank,
           lambda data: f"Rank {_plural(data['issues'])} "
                        f"{'before ' + data['before'] if data.get('before') else 'after ' + str(data.get('after'))}.",
           lambda ctx, data: (ctx.client.rank(data["issues"], before=data.get("before"), after=data.get("after")),
                              {"issues": data["issues"]})[1],
           undo="Rank them again."),
    Action("create_sprint", "Create a sprint", "A new, not yet started sprint on a board.", "medium", "software_write",
           (Param("board", "number", "Board", True), Param("name", "text", "Name", True),
            Param("goal", "longtext", "Goal"), Param("startDate", "date", "Start"),
            Param("endDate", "date", "End")), _clean_create_sprint,
           lambda data: f"Create the sprint '{data['name']}' on board {data['board']}.",
           lambda ctx, data: {"sprintId": ctx.client.create_sprint(
               board_id=data["board"], name=data["name"], goal=data.get("goal"),
               start_date=f"{data['startDate']}T09:00:00.000Z" if data.get("startDate") else None,
               end_date=f"{data['endDate']}T17:00:00.000Z" if data.get("endDate") else None).get("id")},
           check=_check_made("sprint", "sprintId"), undo="Delete the empty sprint in Jira."),
    Action("start_sprint", "Start a sprint", "Start a planned sprint. The team is notified.", "high", "software_write",
           (Param("sprint", "number", "Sprint", True), Param("startDate", "date", "Start"),
            Param("endDate", "date", "End", True)), _clean_start_sprint,
           lambda data: f"Start the sprint {(data.get('_sprint') or {}).get('name') or data['sprint']}, "
                        f"ending {data['endDate']}.",
           _run_start_sprint, resolve=_resolve_start_sprint, check=_check_sprint_state("active"),
           undo="A started sprint cannot be un-started; it can be completed."),
    Action("complete_sprint", "Complete a sprint", "Close the running sprint.", "high", "software_write",
           (Param("sprint", "number", "Sprint", True),), _clean_sprint_only, _preview_complete_sprint,
           lambda ctx, data: (ctx.client.update_sprint(data["sprint"], {"state": "closed"}),
                              {"sprintId": data["sprint"], "state": "closed"})[1],
           resolve=_resolve_complete_sprint, check=_check_sprint_state("closed"),
           undo="A completed sprint cannot be reopened from the Desk."),
    Action("create_version", "Create a release", "A new version in a project.", "medium", "project_admin",
           (Param("project", "project", "Project", True), Param("name", "text", "Name", True),
            Param("description", "longtext", "Description"), Param("startDate", "date", "Start"),
            Param("releaseDate", "date", "Release date")), _clean_create_version,
           lambda data: f"Create the version '{data['name']}' in {data['project']}"
                        f"{', releasing ' + data['releaseDate'] if data.get('releaseDate') else ''}.",
           _run_create_version, check=_check_made("version", "versionId"), undo="Delete the version in Jira."),
    Action("release_version", "Release a version", "Mark a version as released.", "high", "project_admin",
           (Param("version", "number", "Version", True), Param("releaseDate", "date", "Release date")),
           _clean_release_version,
           lambda data: f"Mark version {data.get('_name') or data['version']} as released"
                        + (f". {data['_open']} of its {data['_total']} issues are still open." if data.get("_open")
                           else ". Every issue in it is resolved." if "_open" in data else "."),
           _run_release_version, resolve=_resolve_release_version, check=_check_release_version,
           undo="Unrelease the version in Jira."),
    Action("answer_approval", "Answer an approval", "Approve or decline a service request.", "high",
           "servicedesk_write",
           (_ISSUE, Param("approval", "number", "Approval", True),
            Param("decision", "choice", "Decision", True, "approve or decline")), _clean_approval,
           lambda data: f"{'Approve' if data['decision'] == 'approve' else 'Decline'} the request {_titled(data)}.",
           _run_approval, resolve=_resolve_before, undo="An answered approval cannot be changed."),
)
ACTION_BY_NAME: Dict[str, Action] = {action.name: action for action in ACTIONS}


def public(data: Mapping[str, Any]) -> Dict[str, Any]:
    """An action's input without what ``resolve`` pinned (keys starting with ``_``)."""
    return {key: value for key, value in data.items() if not str(key).startswith("_")}
