"""An errand on a website as part of a Desk run: fetch a report from an
authorised portal, bring its figures into a workbook, tell someone.

One run, one record. The run that was opened for the message carries all of
it: the browser's steps as ``browser`` events, the retrieved file among the
run's files, the workbook change as a ``file`` change the person applies, and
the email as Scriba's own ``send_email`` card. Nothing here is a second
engine: the browser is a tool (``browser.run_task``), the workbook change is
``workbooks``, the email is the card path every other reply uses.

What runs without asking: opening, reading and downloading on a site the
person authorised. What waits for the person: the workbook change (they
apply it) and the email (they approve it).

Everything is decided by rule. No model reads the page, the file or the
message here.
"""
from __future__ import annotations

import io
import os
import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import browser, files, lifecycle, workbooks

_FETCH = re.compile(r"\b(download|fetch|get|retrieve|pull|grab|collect)\b", re.I)
_REPORT = re.compile(r"\b(report|statement|figures|workbook|spreadsheet)\b", re.I)
_PLACE = re.compile(r"\b(portal|website|web site|site|extranet)\b", re.I)
_UPDATE = re.compile(r"\bupdate\b[^.\n]{0,80}\b(workbook|spreadsheet|sheet|file)\b", re.I)
_SEND = re.compile(r"\bsend\b[^\n]{0,200}", re.I)
_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
RETRIES = 1                      # an interrupted errand is taken up again once, from the record


def request(subject: str, text: str) -> Optional[Dict[str, Any]]:
    """Does the message ask for a report to be fetched from a website? What
    else does it ask to be done with it? Words of the message only."""
    combined = f"{subject or ''}\n{text or ''}"
    if not (_FETCH.search(combined) and _REPORT.search(combined) and _PLACE.search(combined)):
        return None
    sending = _SEND.search(combined)
    return {"updateWorkbook": bool(_UPDATE.search(combined)), "send": bool(sending),
            "recipients": sorted(set(_ADDRESS.findall(sending.group(0)))) if sending else []}


def match_site(sites: List[Mapping[str, Any]], text: str) -> Tuple[Optional[Mapping[str, Any]], str]:
    """The one authorised site the message names. An address written in the
    message is never browsed for being written there."""
    low = str(text or "").lower()
    found = [site for site in sites
             if any(alias and alias.lower() in low for alias in [site.get("name"), *(site.get("aliases") or [])])]
    if len(found) == 1:
        return found[0], "matched"
    return None, "site_not_authorised" if not found else "site_ambiguous"


def retrieval_task(site: Mapping[str, Any]) -> Dict[str, Any]:
    """The latest report of a portal: its section, the newest entry, what the
    page says about it, the file. The names are the site's own, kept with it."""
    how = site.get("reports") or {}
    return {"goal": "Retrieve the latest report", "ops": [
        {"op": "open", "path": site.get("start") or "/"},
        {"op": "follow", "name": how.get("section") or "Reports"},
        {"op": "follow", "name": how.get("entry") or "report", "pick": "latest"},
        {"op": "read", "label": how.get("period") or "Period", "name": "period"},
        {"op": "download", "name": how.get("download") or "Download", "kind": "xlsx",
         "checksum": how.get("checksum") or "SHA-256"}]}


def _rows(content: bytes) -> List[Tuple[str, List[str], List[List[Any]]]]:
    import openpyxl

    book = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=False)
    out = []
    for sheet in book.worksheets:
        rows = [list(row) for row in sheet.iter_rows(values_only=True, max_row=2000)]
        if rows and any(cell is not None for cell in rows[0]):
            out.append((sheet.title, [str(cell).strip() if cell is not None else "" for cell in rows[0]], rows[1:]))
    book.close()
    return out


def derive_operations(report: bytes, workbook: bytes) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """The rows of the report as changes to the workbook, or why none can be
    derived. A plain rule: the report's first column is the key; the workbook
    sheet that has that column and at least one other column of the report
    takes each row's shared columns. Nothing is guessed: no shared columns,
    no change."""
    try:
        source, target = _rows(report), _rows(workbook)
    except Exception:
        return [], "One of the two files could not be opened as a workbook."
    if not source or not target:
        return [], "One of the two files has no table with a header row."
    _, headers, rows = source[0]
    key = headers[0]
    for title, theirs, _ in target:
        shared = [h for h in headers[1:] if h and h in theirs]
        if key and key in theirs and shared:
            operations = []
            for row in rows:
                values = dict(zip(headers, row))
                if values.get(key) in (None, ""):
                    continue
                if any(isinstance(values.get(h), str) and str(values[h]).startswith("=") for h in shared):
                    return [], "The report holds formulas where figures were expected."
                operations.append({"op": "upsert_row", "sheet": title, "key": key,
                                   "values": {key: values[key], **{h: values[h] for h in shared if values.get(h) is not None}}})
            return (operations[:workbooks.MAX_OPERATIONS], None) if operations else ([], "The report has no rows.")
    return [], f"No sheet of the workbook has the report's \"{key}\" column and one of its figures columns."


def state(events: List[Mapping[str, Any]]) -> Optional[Dict[str, Any]]:
    """The run's errand as its record tells it, or None when it has none."""
    planned, steps, result, attempts, submitting = None, [], None, 0, False
    for item in events:
        if item.get("kind") != "browser":
            continue
        data = dict(item.get("data") or {})
        phase = data.pop("phase", None)
        if phase == "planned":
            planned = data
        elif phase == "started":
            attempts, steps, result = attempts + 1, [], None
        elif phase == "step":
            steps = [s for s in steps if s.get("index") != data.get("index") or s.get("state") == "done"]
            steps.append({**data, "at": item.get("at")})
        elif phase == "result":
            result = {**data, "at": item.get("at")}
    if planned is None:
        return None
    return {"planned": planned, "steps": steps, "result": result, "attempts": attempts}


def plan(workflow: Any, user: Any, item: Dict[str, Any], plan: Dict[str, Any], attached: List[Dict[str, Any]]) -> None:
    """At planning time: is this an errand, on which site, with which
    workbook? Reads nothing from the web yet."""
    text = f"{item.get('subject') or ''}\n{item.get('body') or item.get('snippet') or ''}"
    asked = request(str(item.get("subject") or ""), str(item.get("body") or item.get("snippet") or ""))
    if asked is None or (plan.get("held") and plan["held"].get("reason") != "needs_review"):
        return
    listing = getattr(workflow.gateway, "sites", None)
    sites = (listing(user) if callable(listing) else None) or []
    site, why = match_site(sites, text)
    if site is None:
        plan["held"] = {
            "reason": "site_not_authorised" if why == "site_not_authorised" else "needs_clarification",
            "slots": [], "calendars": [],
            "message": ("The message asks for something from a website that is not one of the sites you have "
                        "authorised. Nothing was opened." if why == "site_not_authorised" else
                        "The message could mean more than one of your authorised sites. Which one?")}
        plan["decisions"].append({"decision": "escalate", "reason": why,
                                  "explanation": "A website is browsed only when it is one you authorised, by name."})
        return
    problems = browser.site_problems(site, sandbox=workflow._world_id(user) is not None)
    if problems:
        plan["held"] = {"reason": "site_not_authorised", "slots": [], "calendars": [], "message": problems[0]}
        plan["decisions"].append({"decision": "escalate", "reason": "site_refused", "explanation": problems[0]})
        return
    book = next((f for f in attached if f.get("read") and f.get("kind") == "xlsx"), None) \
        if asked["updateWorkbook"] else None
    if plan.get("held"):
        plan["held"] = None
    plan["proposals"] = [p for p in plan["proposals"] if p.get("purpose") != "review_file"]
    plan["deferred"] = [d for d in plan.get("deferred") or [] if d.get("purpose") != "reply"]
    reply = workflow._reply_input(item, "")
    if asked["recipients"]:
        reply.update(to=", ".join(asked["recipients"]), mode="new", subject=str(item.get("subject") or "Report"))
    plan["errand"] = {
        "site": site.get("id"), "siteName": site.get("name"), "origin": site.get("origin"),
        "task": retrieval_task(site), "goal": "Retrieve the latest report",
        "workbookFileId": (book or {}).get("attachmentId"), "workbookName": (book or {}).get("filename"),
        "wantsWorkbook": asked["updateWorkbook"], "wantsEmail": asked["send"], "email": reply}
    plan.setdefault("facts", []).append(f"\"{site.get('name')}\" is one of your authorised sites.")
    plan["decisions"].append({
        "decision": "proceed", "reason": "errand_on_authorised_site",
        "explanation": f"The report is fetched from {site.get('name')} without asking: that only reads. "
                       + ("The workbook change waits for you to apply it. " if book else "")
                       + ("The email waits for your approval." if asked["send"] else "")})
    if asked["updateWorkbook"] and book is None:
        plan["decisions"].append({"decision": "note", "reason": "no_workbook_attached",
                                  "explanation": "The message asks for a workbook to be updated and brings none "
                                                 "that could be read. The report is fetched; nothing is changed."})


def _sessions(workflow: Any) -> browser.Sessions:
    if getattr(workflow, "browser_sessions", None) is None:
        workflow.browser_sessions = browser.Sessions(os.environ.get("SCRIBA_BACKEND_PATH", ""))
    return workflow.browser_sessions


def _site(workflow: Any, user: Any, site_id: Any) -> Optional[Mapping[str, Any]]:
    listing = getattr(workflow.gateway, "sites", None)
    return next((s for s in (listing(user) if callable(listing) else None) or [] if s.get("id") == site_id), None)


def _fetch(workflow: Any, user: Any, run: Dict[str, Any], planned: Mapping[str, Any]) -> None:
    site = _site(workflow, user, planned.get("site"))
    record = lambda data: workflow._record(user, run, "browser", data)       # noqa: E731
    if site is None or browser.site_problems(site, sandbox=workflow._world_id(user) is not None):
        record({"phase": "result", "state": "FAILED", "error": "site_not_authorised",
                "message": "The site is no longer one of your authorised sites. Nothing was opened."})
        return
    sessions = _sessions(workflow)
    status = sessions.status()
    if not status["available"]:
        record({"phase": "result", "state": "FAILED", "error": status["reason"], "message": status["message"]})
        return
    record({"phase": "started", "site": site.get("name"), "origin": site.get("origin")})
    result = browser.run_task(sessions.session(str(getattr(user, "id", user)), site), planned["task"],
                              record=lambda step: record({"phase": "step", **step}))
    kept = []
    for download in result.get("downloads") or []:
        keep = getattr(workflow.gateway, "keep_download", None)
        stored = keep(user, filename=download["filename"], content=download["content"],
                      mime_type=str(download.get("mimeType") or workbooks.XLSX_MIME)) if callable(keep) else None
        back = workflow.gateway.stored_file(user, str(stored["id"])) if stored else None
        if not back or back["sha256"] != download["sha256"]:
            result.update(state="FAILED", error="file_not_kept",
                          message="The file was downloaded and could not be kept in your records.")
            continue
        kept.append({"fileId": str(stored["id"]), "filename": download["filename"], "sizeBytes": download["sizeBytes"],
                     "sha256": download["sha256"], "kind": download.get("kind"), "from": download.get("from"),
                     "verified": True, "checksum": download.get("checksum")})
    record({"phase": "result", **{k: result.get(k) for k in (
        "state", "error", "message", "values", "untrustedFindings", "ignored", "blockedOrigins", "actions",
        "requests", "modelCalls", "ms", "stepsDone", "stepsTotal")}, "downloads": kept})


def advance(workflow: Any, ctx: Any, user: Any, run: Dict[str, Any]) -> None:
    """Take the errand as far as it may go without the person. Driven by the
    record only, so it is safe to call again and again."""
    events = workflow.gateway.run_events(user, run)
    errand = state(events)
    if errand is None:
        return
    planned, result = errand["planned"], errand["result"]
    if result is None or (result.get("state") == "INTERRUPTED" and errand["attempts"] <= RETRIES):
        _fetch(workflow, user, run, planned)
        errand = state(workflow.gateway.run_events(user, run))
        result = errand["result"]
    if not result or result.get("state") != "VERIFIED" or not result.get("downloads"):
        return
    report = result["downloads"][0]
    events = workflow.gateway.run_events(user, run)
    changes = [c for c in lifecycle.file_changes(events) if c.get("from") == "errand"]
    decided = {(e.get("data") or {}).get("reason") for e in events if e.get("kind") == "decision"}
    if planned.get("workbookFileId") and not changes and "workbook_not_mapped" not in decided:
        source = workflow.gateway.stored_file(user, str(planned["workbookFileId"]))
        fetched = workflow.gateway.stored_file(user, report["fileId"])
        operations, why = derive_operations(fetched["content"], source["content"]) if source and fetched \
            else ([], "The workbook is no longer in your records.")
        clean, problems = workbooks.validate(operations) if operations else ([], [why])
        if problems:
            workflow._record(user, run, "decision", {
                "decision": "escalate", "reason": "workbook_not_mapped",
                "explanation": f"The report was fetched. The workbook was not changed: {problems[0]}"})
        else:
            known = lifecycle.file_changes(events)
            workflow._record(user, run, "file", {
                "changeId": f"fc-{run['id']}-{len(known) + 1}", "op": "change_workbook", "state": "suggested",
                "sourceFileId": str(source["id"]), "filename": source["filename"], "sourceSha256": source["sha256"],
                "operations": clean, "binding": workbooks.binding(source["sha256"], clean), "by": "desk",
                "from": "errand", "basedOnFileId": report["fileId"]})
        return
    if not planned.get("wantsEmail"):
        return
    change = changes[-1] if changes else None
    if planned.get("workbookFileId") and (change is None or change.get("state") != "applied"):
        return                               # the email speaks of the updated workbook: not before it exists
    if any(e.get("kind") == "proposal" and (e.get("data") or {}).get("purpose") == "send_report" for e in events):
        return
    period = (result.get("values") or {}).get("period")
    lines = [f"The latest report from {planned.get('siteName')}" + (f" ({period})" if period else "")
             + f" has been retrieved: \"{report['filename']}\"."]
    if change is not None:
        rows = len(change.get("operations") or [])
        lines.append(f"Its figures are now in \"{change.get('resultFilename')}\" ({rows} row{'s' if rows != 1 else ''} "
                     "updated). The original workbook was left as it was.")
    lines.append("The files are in my records and are not attached to this message.")
    workflow._propose(user, run, {
        "tool_name": "send_email", "purpose": "send_report",
        "reason": "The report was retrieved and verified" + (", and the workbook change was applied" if change else "")
                  + ". You approve or change the wording and the recipients.",
        "tool_input": {**planned["email"], "body": "\n\n".join(lines)}})


def view(events: List[Mapping[str, Any]], simulated: bool) -> Optional[Dict[str, Any]]:
    """The errand as the person sees it. No page text, no cookie, no query string."""
    errand = state(events)
    if errand is None:
        return None
    planned, result = errand["planned"], errand["result"] or {}
    return {
        "state": result.get("state") or ("RUNNING" if errand["attempts"] else "PLANNED"),
        "site": planned.get("siteName"), "origin": planned.get("origin"), "goal": planned.get("goal"),
        "attempts": errand["attempts"], "steps": errand["steps"],
        "stepsDone": sum(1 for step in errand["steps"] if step.get("state") == "done"),
        "stepsTotal": len((planned.get("task") or {}).get("ops") or []),
        "values": result.get("values") or {},
        "downloads": [{**d, "download": {"method": "GET", "path": f"/desk/files/{d['fileId']}"}}
                      for d in result.get("downloads") or []],
        "untrustedFindings": result.get("untrustedFindings") or [], "ignored": result.get("ignored") or [],
        "blockedOrigins": result.get("blockedOrigins") or [],
        "actions": result.get("actions"), "requests": result.get("requests"), "modelCalls": 0, "ms": result.get("ms"),
        "error": result.get("error"), "message": result.get("message"),
        "verified": result.get("state") == "VERIFIED", "simulated": simulated,
    }
