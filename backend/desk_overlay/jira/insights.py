"""What an executive needs from a set of issues. Pure.

Jira answers "what are the issues". A person running a team asks something
else: what is late, what is stuck, what is waiting on me, is the sprint going
to land, is the release on track, who is overloaded. These functions answer
those from issues already normalized by ``models.py``; they read nothing and
call nothing.

Every figure is a count of the rows it was given. When the caller passed a
truncated list the result says so (``complete``): a short list is never
presented as the whole picture.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from .models import parse_instant

SECTION_LIMIT = 8
DUE_SOON_DAYS = 7


def _rank(issue: Mapping[str, Any]) -> tuple:
    """Most pressing first: the higher priority, then the earlier due date."""
    priority = (issue.get("priority") or {}).get("rank", 3)
    return (priority, issue.get("due") or "9999-12-31", issue.get("updated") or "")


def _is(issue: Mapping[str, Any], signal: str) -> bool:
    return bool((issue.get("signals") or {}).get(signal))


def _open(issue: Mapping[str, Any]) -> bool:
    return (issue.get("status") or {}).get("category") != "done"


def _mine(issue: Mapping[str, Any], me: Optional[str]) -> bool:
    return bool(me) and (issue.get("assignee") or {}).get("accountId") == me


def _section(section_id: str, title: str, why: str, rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    ordered = sorted(rows, key=_rank)
    return {"id": section_id, "title": title, "why": why, "count": len(ordered),
            "issues": ordered[:SECTION_LIMIT], "truncated": len(ordered) > SECTION_LIMIT}


def digest(issues: Iterable[Mapping[str, Any]], *, me: Optional[str] = None,
           complete: bool = True) -> Dict[str, Any]:
    """The briefing: what needs this person, most pressing first.

    An issue appears in the FIRST section it fits, so the same issue is not
    listed three times because it is late, blocked and high priority at once.
    """
    rows = [issue for issue in issues if _open(issue)]
    placed: set = set()

    def take(predicate: Any) -> List[Mapping[str, Any]]:
        chosen = [issue for issue in rows if issue.get("key") not in placed and predicate(issue)]
        placed.update(issue.get("key") for issue in chosen)
        return chosen

    def due_soon(issue: Mapping[str, Any]) -> bool:
        days = (issue.get("signals") or {}).get("dueInDays")
        return days is not None and 0 <= days <= DUE_SOON_DAYS

    sections = [
        _section("overdue", "Overdue", "Open and past the due date.",
                 take(lambda issue: _is(issue, "overdue"))),
        _section("blocked", "Blocked", "Flagged, in a blocked status, or waiting on an open issue.",
                 take(lambda issue: _is(issue, "blocked"))),
        _section("due_soon", "Due this week", f"Due in the next {DUE_SOON_DAYS} days.", take(due_soon)),
        _section("mine_high", "Yours, high priority", "Assigned to you at the two highest priorities.",
                 take(lambda issue: _mine(issue, me) and (issue.get("priority") or {}).get("rank", 3) <= 2)),
        _section("stale", "Stalled", "In progress and untouched for a week.",
                 take(lambda issue: _is(issue, "stale"))),
        _section("unowned", "Nobody owns these", "High priority and unassigned.",
                 take(lambda issue: _is(issue, "unassigned")
                      and (issue.get("priority") or {}).get("rank", 3) <= 2)),
    ]
    return {
        "counts": {
            "open": len(rows),
            "mine": sum(1 for issue in rows if _mine(issue, me)),
            "overdue": sum(1 for issue in rows if _is(issue, "overdue")),
            "blocked": sum(1 for issue in rows if _is(issue, "blocked")),
            "dueSoon": sum(1 for issue in rows if due_soon(issue)),
            "stale": sum(1 for issue in rows if _is(issue, "stale")),
            "unassigned": sum(1 for issue in rows if _is(issue, "unassigned")),
        },
        "sections": [section for section in sections if section["count"]],
        "complete": bool(complete),
    }


def _points(issues: Iterable[Mapping[str, Any]]) -> float:
    return float(sum(issue.get("storyPoints") or 0 for issue in issues))


def progress(issues: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Done, in progress and to do, by count and by story points."""
    by_category: Dict[str, List[Mapping[str, Any]]] = {"todo": [], "in_progress": [], "done": []}
    for issue in issues:
        by_category.setdefault((issue.get("status") or {}).get("category") or "todo", []).append(issue)
    total, total_points = len(issues), _points(issues)
    estimated = sum(1 for issue in issues if issue.get("storyPoints") is not None)
    return {
        "total": total,
        "todo": len(by_category["todo"]), "inProgress": len(by_category["in_progress"]),
        "done": len(by_category["done"]),
        "percentDone": round(100 * len(by_category["done"]) / total) if total else None,
        "points": {
            "total": total_points, "done": _points(by_category["done"]),
            "percentDone": round(100 * _points(by_category["done"]) / total_points) if total_points else None,
            # Points only mean something when most of the work carries them.
            "estimatedShare": round(100 * estimated / total) if total else None,
        },
    }


def sprint_health(sprint: Mapping[str, Any], issues: Sequence[Mapping[str, Any]], *,
                  now: dt.datetime, complete: bool = True) -> Dict[str, Any]:
    """Is this sprint going to land. A comparison of work done with time gone:
    a sprint two thirds over with a third of the work done is at risk."""
    done = progress(issues)
    start, end = parse_instant(sprint.get("startDate")), parse_instant(sprint.get("endDate"))
    elapsed: Optional[int] = None
    days_left: Optional[int] = None
    if start and end and end > start:
        span = (end - start).total_seconds()
        elapsed = max(0, min(100, round(100 * (now - start).total_seconds() / span)))
        days_left = max(0, (end.date() - now.date()).days)
    use_points = bool(done["points"]["total"]) and (done["points"]["estimatedShare"] or 0) >= 60
    percent = done["points"]["percentDone"] if use_points else done["percentDone"]
    blocked = [issue["key"] for issue in issues if _is(issue, "blocked")]
    unassigned = [issue["key"] for issue in issues if _is(issue, "unassigned")]
    reasons: List[str] = []
    active = str(sprint.get("state") or "") == "active"
    if active and elapsed is not None and percent is not None and elapsed - percent >= 25:
        reasons.append(f"{elapsed}% of the time has gone and {percent}% of the work is done.")
    if active and end and now > end:
        reasons.append("The sprint is past its end date and still open.")
    if blocked:
        reasons.append(f"{len(blocked)} issue{'s are' if len(blocked) != 1 else ' is'} blocked.")
    if active and days_left is not None and days_left <= 2 and done["todo"]:
        reasons.append(f"{done['todo']} issue{'s have' if done['todo'] != 1 else ' has'} not been started "
                       f"with {days_left} day{'s' if days_left != 1 else ''} left.")
    return {
        "sprint": dict(sprint), "progress": done, "measuredIn": "points" if use_points else "issues",
        "percentDone": percent, "percentElapsed": elapsed, "daysLeft": days_left,
        "blocked": blocked, "unassigned": unassigned,
        "atRisk": bool(reasons), "reasons": reasons, "complete": bool(complete),
    }


def release_progress(version: Mapping[str, Any], issues: Sequence[Mapping[str, Any]], *,
                     complete: bool = True) -> Dict[str, Any]:
    done = progress(issues)
    open_rows = [issue for issue in issues if _open(issue)]
    reasons: List[str] = []
    days = version.get("daysToRelease")
    if version.get("overdue"):
        reasons.append("The release date has passed and the version is not released.")
    elif days is not None and days <= 7 and open_rows:
        reasons.append(f"{len(open_rows)} open issue{'s' if len(open_rows) != 1 else ''} "
                       f"with {days} day{'s' if days != 1 else ''} to the release date.")
    blocked = [issue["key"] for issue in open_rows if _is(issue, "blocked")]
    if blocked:
        reasons.append(f"{len(blocked)} open issue{'s are' if len(blocked) != 1 else ' is'} blocked.")
    return {"version": dict(version), "progress": done, "open": sorted(open_rows, key=_rank)[:SECTION_LIMIT],
            "blocked": blocked, "atRisk": bool(reasons), "reasons": reasons, "complete": bool(complete)}


def workload(issues: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Open work per person, heaviest first. Unassigned work is its own row."""
    rows: Dict[str, Dict[str, Any]] = {}
    for issue in issues:
        if not _open(issue):
            continue
        person = issue.get("assignee") or {}
        key = str(person.get("accountId") or "")
        row = rows.setdefault(key, {"assignee": person or None, "open": 0, "inProgress": 0,
                                    "overdue": 0, "blocked": 0, "points": 0.0})
        row["open"] += 1
        row["inProgress"] += 1 if (issue.get("status") or {}).get("category") == "in_progress" else 0
        row["overdue"] += 1 if _is(issue, "overdue") else 0
        row["blocked"] += 1 if _is(issue, "blocked") else 0
        row["points"] += float(issue.get("storyPoints") or 0)
    return sorted(rows.values(), key=lambda row: (-row["open"], -row["overdue"]))
