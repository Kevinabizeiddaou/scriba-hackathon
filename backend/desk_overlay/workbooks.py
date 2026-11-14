"""Changing a workbook, through Scriba's own Excel skills. An adapter: no
cell is written by Desk code.

Scriba's desktop agent has skills that edit a workbook safely
(``desktop_agent/skills/excel.py``, dispatched by ``skills.registry.run_job``):
each one backs the file up, writes, reads the written cells back, checks that
every sheet and every formula is still there, and restores the backup if not.
They also refuse a path outside the folders they were given, and a workbook
with features that an edit would silently drop.

Here those same skills run on a COPY, in a temporary folder that is the only
folder they are allowed to touch and that is removed afterwards:

    xlsx.update_cell   one cell, by its A1 reference
    xlsx.append_row    one row, by column header (a totals row stays last and
                       its range grows)
    xlsx.upsert_row    update the row whose key column matches, else add it

Rules this module keeps:

- **The original is never touched.** The result is a new file.
- **All or nothing.** If any operation fails, nothing is kept: no file is
  produced, and the answer says which operation failed and why.
- **No formula is written.** A value that starts with ``=``, ``+``, ``-`` or
  ``@`` followed by a letter is refused: a value is data.
- **Verified twice.** Each skill verifies its own write; then the result is
  reopened with Scriba's reader and compared with the original: same sheets,
  no formula lost, and exactly the number of rows the operations account for.
- What to change is decided by whoever proposes the change. This module only
  checks that the operations are well formed, runs them and verifies them.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import files

OPERATIONS = ("update_cell", "append_row", "upsert_row")
MAX_OPERATIONS = 50
MAX_TEXT = 2_000
_CELL = re.compile(r"^[A-Za-z]{1,3}[1-9]\d{0,6}$")
_FORMULA = re.compile(r"^\s*(?:=|@|[+\-](?=\s*[A-Za-z(]))")
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _value_problem(value: Any) -> Optional[str]:
    if value is None or isinstance(value, (bool, int, float)):
        return None
    if not isinstance(value, str):
        return "a value must be text, a number, true, false or empty"
    if len(value) > MAX_TEXT:
        return f"a value is longer than {MAX_TEXT} characters"
    if _FORMULA.match(value):
        return "a value that starts like a formula is not written"
    return None


def validate(operations: Any) -> Tuple[List[Dict[str, Any]], List[str]]:
    """The operations in a fixed shape, and what is wrong with them. Nothing
    is guessed: an operation with a problem is not repaired."""
    problems: List[str] = []
    clean: List[Dict[str, Any]] = []
    if not isinstance(operations, list) or not operations:
        return [], ["At least one operation is needed."]
    if len(operations) > MAX_OPERATIONS:
        return [], [f"At most {MAX_OPERATIONS} operations can be applied at once."]
    for index, raw in enumerate(operations, start=1):
        where = f"Operation {index}"
        if not isinstance(raw, Mapping) or raw.get("op") not in OPERATIONS:
            problems.append(f"{where}: op must be one of {', '.join(OPERATIONS)}.")
            continue
        sheet = str(raw.get("sheet") or "").strip()
        if not sheet or len(sheet) > 100:
            problems.append(f"{where}: name the sheet.")
            continue
        if raw["op"] == "update_cell":
            cell = str(raw.get("cell") or "").strip().upper()
            if not _CELL.match(cell):
                problems.append(f"{where}: cell must be a reference such as C4.")
                continue
            issue = _value_problem(raw.get("value"))
            if issue:
                problems.append(f"{where}: {issue}.")
                continue
            clean.append({"op": "update_cell", "sheet": sheet, "cell": cell, "value": raw.get("value")})
            continue
        values = raw.get("values")
        if not isinstance(values, Mapping) or not values or len(values) > 100:
            problems.append(f"{where}: values must map column headers to values.")
            continue
        issues = [f"\"{header}\": {_value_problem(value)}" for header, value in values.items() if _value_problem(value)]
        if issues or any(not str(header).strip() for header in values):
            problems.append(f"{where}: {'; '.join(issues) or 'a column header is empty'}.")
            continue
        entry: Dict[str, Any] = {"op": raw["op"], "sheet": sheet, "values": {str(k): v for k, v in values.items()}}
        if raw["op"] == "upsert_row":
            key = str(raw.get("key") or "").strip()
            if key not in entry["values"]:
                problems.append(f"{where}: key must be one of the columns in values.")
                continue
            entry["key"] = key
        clean.append(entry)
    return clean, problems


def binding(source_sha256: str, operations: List[Mapping[str, Any]]) -> str:
    """What an approval of a change is bound to: this exact file and these
    exact operations."""
    material = json.dumps({"source": source_sha256, "operations": operations}, sort_keys=True, default=str)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _job(operation: Mapping[str, Any], path: str) -> Dict[str, Any]:
    if operation["op"] == "update_cell":
        return {"job_type": "xlsx.update_cell", "payload": {
            "path": path, "sheet_name": operation["sheet"], "cell": operation["cell"], "value": operation["value"]}}
    payload: Dict[str, Any] = {"path": path, "sheet_name": operation["sheet"], "columns": dict(operation["values"])}
    if operation["op"] == "upsert_row":
        payload["key_column"] = operation["key"]
    return {"job_type": f"xlsx.{operation['op']}", "payload": payload}


def apply(filename: str, content: bytes, operations: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """Run the operations with Scriba's skills on a copy. Returns the new
    file's bytes, or why there is none. The original bytes are only read."""
    from desktop_agent.skills.registry import SkillContext, run_job

    info = files.inspect(filename, content)
    if not info["ok"] or info["kind"] != "xlsx":
        return {"ok": False, "code": "not_a_workbook", "steps": [],
                "message": "Only an .xlsx workbook can be changed. " + str(info.get("message") or "")}
    folder = tempfile.mkdtemp(prefix="desk-workbook-")
    steps: List[Dict[str, Any]] = []
    try:
        path = os.path.join(folder, "workbook.xlsx")
        with open(path, "wb") as handle:
            handle.write(content)
        context = SkillContext(allowed_roots=[folder])
        for index, operation in enumerate(operations, start=1):
            outcome = run_job({"id": index, **_job(operation, path)}, context)
            result = outcome.result or {}
            check = result.get("verification") if isinstance(result.get("verification"), Mapping) else {}
            step = {"index": index, "op": operation["op"], "sheet": operation["sheet"],
                    "status": outcome.status, "verified": bool(check.get("verified")),
                    "cell": result.get("cell"), "row": result.get("row_index"), "matched": result.get("matched"),
                    "oldValue": result.get("old_value"), "oldValues": result.get("old_values"),
                    "formulasKept": check.get("formulas_kept"), "cellsChecked": check.get("cells_checked"),
                    "error": outcome.error, "stage": outcome.failure_stage}
            steps.append(step)
            if outcome.status != "succeeded" or not step["verified"]:
                # The skill restored its own backup; the copy is discarded anyway.
                return {"ok": False, "code": "operation_failed", "failedAt": index, "steps": steps,
                        "message": f"Operation {index} did not take effect"
                                   + (f": {outcome.error}" if outcome.error else " (it could not be verified)")
                                   + ". Nothing was kept; the original is unchanged."}
        with open(path, "rb") as handle:
            changed = handle.read()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return {"ok": True, "content": changed, "sha256": files.sha256(changed), "steps": steps}


def _layout(filename: str, content: bytes) -> Optional[Dict[str, Dict[str, Any]]]:
    found = files.read(filename, content)
    if not found["read"] or found["kind"] != "xlsx":
        return None
    return {str(sheet["name"]): {"rows": int(sheet.get("rows") or 0), "formulas": int(sheet.get("formulas") or 0)}
            for sheet in found["sheets"]}


def verify(filename: str, original: bytes, changed: bytes, operations: List[Mapping[str, Any]],
           steps: List[Mapping[str, Any]]) -> Dict[str, Any]:
    """Reopen the result with Scriba's reader and compare it with the
    original. Independent of the skills' own checks."""
    before, after = _layout(filename, original), _layout(filename, changed)
    if before is None:
        return {"ok": False, "reason": "original_unreadable"}
    if after is None:
        return {"ok": False, "reason": "result_unreadable"}
    if list(before) != list(after):
        return {"ok": False, "reason": "sheets_differ", "before": list(before), "after": list(after)}
    added: Dict[str, int] = {}
    for operation, step in zip(operations, steps):
        if operation["op"] == "append_row" or (operation["op"] == "upsert_row" and step.get("matched") is False):
            added[operation["sheet"]] = added.get(operation["sheet"], 0) + 1
    for name, layout in before.items():
        if after[name]["formulas"] < layout["formulas"]:
            return {"ok": False, "reason": "formula_lost", "sheet": name}
        expected = layout["rows"] + added.get(name, 0)
        # A cell written below the last used row makes the sheet that much longer, and no more.
        reach = max([int(re.sub(r"[A-Za-z]", "", op["cell"])) for op in operations
                     if op["op"] == "update_cell" and op["sheet"] == name] or [0])
        if not expected <= after[name]["rows"] <= max(expected, reach):
            return {"ok": False, "reason": "row_count_unexpected", "sheet": name,
                    "expected": expected, "found": after[name]["rows"]}
    if changed == original:
        return {"ok": False, "reason": "nothing_changed"}
    return {"ok": True, "reason": None, "sheets": len(after), "rowsAdded": sum(added.values()),
            "formulas": sum(layout["formulas"] for layout in after.values())}


def result_name(filename: str) -> str:
    stem = re.sub(r"\.xlsx$", "", str(filename or "workbook"), flags=re.I)[:100]
    return f"{stem} (updated).xlsx"
