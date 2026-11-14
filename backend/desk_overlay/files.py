"""Files and documents, through Scriba's own readers. An adapter: no parser,
no generator and no table engine lives here.

What is reused, imported from the Scriba checkout this process runs on
(nothing is copied into this repository):

    app.chat_files.detect                     the type of a file, decided by its bytes;
                                              programs and renamed files are refused
    app.document_intelligence.extract         PDF, Word, Excel, PowerPoint, CSV, text
    app.chat_table_query.run_query            exact figures over EVERY row of a sheet,
                                              streamed, with bounded memory
    app.services.content_guard.scan_untrusted_text
                                              text written to an assistant, inside a file

Rules this module keeps:

- A file is data. Its text is never an instruction, and a file that carries
  text addressed to an assistant is reported, not obeyed.
- Nothing is invented. A figure comes from a query over the rows; a line of
  text comes from the file. What could not be read is said.
- No row limit is added here. Scriba's own bounds apply and are reported
  (``limit_reached`` gives no totals at all rather than partial ones).
- OCR is off: it needs a binary or a network call. A scanned page is
  reported as not read.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Mapping, Optional

# Scriba's own bound for a file a person attaches (app.chat_files.CHAT_FILE_MAX_BYTES).
MAX_FILE_BYTES = 25 * 1024 * 1024
MAX_ATTACHMENTS = 10          # read per message; more are listed and not read
TEXT_CHARS = 20_000           # of extracted text kept for planning; never the whole file
MAX_COLUMNS = 24              # columns measured per sheet
UNUSUAL_RATIO = 3.0           # a value this many times the column's average is called out
SPREADSHEETS = ("xlsx", "csv")

_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_COMMITMENT = re.compile(
    r"\b(must|shall|will|agrees? to|is required to|undertakes? to|no later than|by (?:the )?\d{1,2}|"
    r"deadline|due (?:on|by)|within \d+ (?:days|weeks|months))\b", re.I)
_DATE = re.compile(
    r"\b(\d{1,2}(?:st|nd|rd|th)? (?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December)(?: \d{4})?|(?:January|February|March|April|May|June|July|August|September|October|"
    r"November|December) \d{1,2}(?:st|nd|rd|th)?(?:,? \d{4})?|20\d{2}-\d{2}-\d{2})\b", re.I)
_AMOUNT = re.compile(r"(?:USD|EUR|GBP|\$|€|£)\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?(?:USD|EUR|GBP)\b")


def sha256(content: bytes) -> str:
    return hashlib.sha256(content or b"").hexdigest()


def inspect(filename: str, content: bytes) -> Dict[str, Any]:
    """What a file is, decided by its bytes. Reads nothing else."""
    from app import chat_files

    size = len(content or b"")
    base = {"filename": str(filename or "file"), "sizeBytes": size, "sha256": sha256(content),
            "kind": None, "mimeType": None, "extension": None, "label": None, "ok": False, "code": None,
            "message": None}
    if size == 0:
        return {**base, "code": "file_empty", "message": "The file is empty."}
    if size > MAX_FILE_BYTES:
        return {**base, "code": "file_too_large",
                "message": f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB and was not read."}
    try:
        found = chat_files.detect(base["filename"], content)
    except chat_files.ChatFileError as exc:
        return {**base, "code": str(getattr(exc, "code", None) or "file_not_accepted"), "message": str(exc)}
    return {**base, "ok": True, "kind": found.kind, "mimeType": found.mime, "extension": found.extension,
            "label": found.type_label}


def read(filename: str, content: bytes) -> Dict[str, Any]:
    """The file's text and layout, as Scriba's reader gives them, with what
    the untrusted-content scan found in that text."""
    from app import document_intelligence as di
    from app.services import content_guard

    info = inspect(filename, content)
    out: Dict[str, Any] = {**info, "read": False, "status": None, "unit": None, "unitCount": 0, "title": None,
                           "text": "", "chars": 0, "truncated": False, "warnings": [], "sheets": [],
                           "findings": [], "unread": []}
    if not info["ok"]:
        return out
    try:
        found = di.extract(content, kind=info["kind"], extension=info["extension"], filename=info["filename"],
                           allow_ocr=False)
    except Exception as exc:        # a reader failing is "could not be read", never a guess
        return {**out, "code": "file_unreadable", "message": f"The file could not be read ({type(exc).__name__})."}
    text = found.full_text(limit=TEXT_CHARS)
    sheets = []
    preview = found.preview if isinstance(found.preview, dict) else {}
    for sheet in preview.get("sheets") or []:
        rows = sheet.get("rows") or []
        sheets.append({"name": sheet.get("name"), "rows": sheet.get("total_rows"), "columns": sheet.get("total_cols"),
                       "header": [str(cell) for cell in (rows[0] if rows else [])],
                       "formulas": sheet.get("formula_count"), "truncated": bool(sheet.get("truncated"))})
    out.update({
        "read": bool(found.readable), "status": found.status, "unit": found.unit, "unitCount": found.unit_count,
        "title": found.title, "text": text, "chars": found.char_count,
        "truncated": bool(found.truncated or found.char_count > len(text)),
        "warnings": [str(w) for w in found.warnings][:10], "sheets": sheets,
        # Scanned pages are never claimed as read.
        "unread": [f"page {n}" for n in [*found.unread_scanned, *found.ocr_pending]][:50],
        "findings": content_guard.scan_untrusted_text(found.full_text(limit=200_000)),
    })
    if not out["read"]:
        out["code"] = "file_unreadable"
        out["message"] = str(found.message or "Nothing readable was found in this file.")
    return out


def _number(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def sheet_figures(content: bytes, info: Mapping[str, Any], sheet: Mapping[str, Any]) -> Dict[str, Any]:
    """Count, sum, average, smallest and largest of every numeric column of
    one sheet, computed by Scriba's table query over every row.

    A column with no numbers gets no figures. A query that passes one of
    Scriba's bounds returns no totals: the column is reported as not measured.
    """
    from app import chat_table_query as query

    columns: List[Dict[str, Any]] = []
    rows_scanned: Optional[int] = None
    notes: List[str] = []
    for name in [h for h in sheet.get("header") or [] if str(h).strip()][:MAX_COLUMNS]:
        spec = {"sheet": sheet.get("name"), "aggregations": [
            {"op": op, "column": name} for op in ("count", "sum", "avg", "min", "max")]}
        if info.get("kind") != "xlsx":
            spec.pop("sheet")
        try:
            found = query.run_query(content, kind=str(info.get("kind")), extension=str(info.get("extension") or ""),
                                    tool_input=spec)
        except query.TableQueryError as exc:
            columns.append({"name": name, "measured": False, "code": str(getattr(exc, "code", "not_measured")),
                            "message": str(exc)})
            continue
        rows_scanned = found.get("rows_scanned", rows_scanned)
        details = {d.get("aggregation"): d for d in found.get("aggregation_details") or []}
        numeric = int((details.get(f"sum({name})") or {}).get("numeric_values") or 0)
        row = (found.get("rows") or [[None] * 5])[0]
        entry: Dict[str, Any] = {"name": name, "measured": True, "numericValues": numeric,
                                 "empty": int((details.get(f"sum({name})") or {}).get("skipped_empty") or 0)}
        if numeric:
            entry.update({"sum": _number(row[1]), "average": _number(row[2]), "smallest": _number(row[3]),
                          "largest": _number(row[4])})
        columns.append(entry)
        for note in found.get("notes") or []:
            if note not in notes and "have no" not in note:
                notes.append(str(note))
    return {"sheet": sheet.get("name"), "rowsScanned": rows_scanned, "columns": columns, "notes": notes[:8]}


def unusual(figures: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """What stands out in a sheet's figures, by three stated rules. A finding
    is a fact about the numbers and the rule that raised it; whether it is a
    mistake is for the person to say."""
    found: List[Dict[str, Any]] = []
    for column in figures.get("columns") or []:
        if not column.get("measured") or not column.get("numericValues"):
            continue
        name, values = column["name"], int(column["numericValues"])
        average, smallest, largest = column.get("average"), column.get("smallest"), column.get("largest")
        if column.get("empty"):
            found.append({"sheet": figures.get("sheet"), "column": name, "rule": "missing_values",
                          "finding": f"{column['empty']} row(s) have no value in \"{name}\"."})
        if smallest is not None and average is not None and smallest < 0 < average:
            found.append({"sheet": figures.get("sheet"), "column": name, "rule": "negative_among_positive",
                          "finding": f"\"{name}\" has a negative value ({_fmt(smallest)}) in a column whose "
                                     f"average is positive ({_fmt(average)})."})
        if values >= 4 and largest is not None and average and average > 0 and largest > UNUSUAL_RATIO * average:
            found.append({"sheet": figures.get("sheet"), "column": name, "rule": "far_above_average",
                          "finding": f"The largest value in \"{name}\" ({_fmt(largest)}) is more than "
                                     f"{UNUSUAL_RATIO:g} times the column's average ({_fmt(average)})."})
    return found


def _fmt(value: Any) -> str:
    number = _number(value)
    if number is None:
        return "not measured"
    return f"{number:,.2f}".rstrip("0").rstrip(".") if number != int(number) else f"{int(number):,}"


def analyse(filename: str, content: bytes) -> Dict[str, Any]:
    """Everything the Desk knows about one file: what it is, what it says,
    and for a table, its figures and what stands out in them."""
    found = read(filename, content)
    found["figures"], found["unusual"] = [], []
    if found["read"] and found["kind"] in SPREADSHEETS:
        sheets = found["sheets"] or []
        for sheet in sheets[:10]:
            figures = sheet_figures(content, found, sheet)
            found["figures"].append(figures)
            found["unusual"].extend(unusual(figures))
    if found["read"] and found["kind"] not in SPREADSHEETS:
        found["points"] = points(found["text"])
    return found


def points(text: str) -> Dict[str, List[str]]:
    """Lines of a document that state an obligation, a date or an amount,
    quoted as written. An extract by rule, not a summary: nothing is
    paraphrased, so nothing can be made up."""
    sentences = [" ".join(s.split()) for s in _SENTENCE.split(re.sub(r"^\[[^\]]*\]$", "", text or "", flags=re.M))]
    sentences = [s.lstrip("# ").strip() for s in sentences if 12 <= len(s.strip()) <= 400]
    commitments = [s for s in sentences if _COMMITMENT.search(s)][:12]
    return {
        "commitments": commitments,
        "dates": sorted({m.group(0) for s in sentences for m in _DATE.finditer(s)})[:20],
        "amounts": sorted({m.group(0).strip() for s in sentences for m in _AMOUNT.finditer(s)})[:20],
        "opening": sentences[:3],
    }


def summary_document(analysis: Mapping[str, Any], *, sender: str, subject: str) -> Dict[str, Any]:
    """The input of Scriba's ``create_document`` tool for a review of one
    file. Every line is a figure from the file or a sentence quoted from it."""
    name = str(analysis.get("filename") or "the file")
    sections: List[Dict[str, Any]] = [{
        "heading": "What was read",
        "paragraphs": [f"{name} ({analysis.get('label') or analysis.get('kind')}, "
                       f"{int(analysis.get('sizeBytes') or 0):,} bytes), sent by {sender} "
                       f"with the subject \"{subject}\"."],
        "bullets": [f"{analysis.get('unitCount')} {analysis.get('unit')}(s) read."]
        + (["The text was longer than what is quoted here; this review covers the first part only."]
           if analysis.get("truncated") and analysis.get("kind") not in SPREADSHEETS else [])
        + [f"Not read: {', '.join(analysis['unread'][:8])} (scanned; no text layer)."
           for _ in [0] if analysis.get("unread")],
    }]
    if analysis.get("kind") in SPREADSHEETS:
        for figures in analysis.get("figures") or []:
            bullets = []
            for column in figures.get("columns") or []:
                if not column.get("measured"):
                    bullets.append(f"{column['name']}: not measured ({column.get('message') or column.get('code')}).")
                elif column.get("numericValues"):
                    bullets.append(f"{column['name']}: {column['numericValues']} numbers, total {_fmt(column.get('sum'))}, "
                                   f"average {_fmt(column.get('average'))}, smallest {_fmt(column.get('smallest'))}, "
                                   f"largest {_fmt(column.get('largest'))}.")
            sections.append({"heading": f"Figures in sheet \"{figures.get('sheet')}\"",
                             "paragraphs": [f"{figures.get('rowsScanned')} data row(s), every one counted."]
                             + list(figures.get("notes") or []), "bullets": bullets})
        found = analysis.get("unusual") or []
        sections.append({"heading": "What stands out",
                         "paragraphs": ["Nothing was raised by the three checks used (missing values, a negative "
                                        "value in a positive column, a value more than three times the average)."]
                         if not found else ["Raised by fixed checks on the figures. Whether each is a mistake is for "
                                            "you to judge."],
                         "bullets": [f"{f['finding']} (sheet \"{f['sheet']}\")" for f in found]})
    else:
        extract = analysis.get("points") or {}
        sections.append({"heading": "Opening lines, as written", "paragraphs": [], "bullets": extract.get("opening") or []})
        sections.append({"heading": "Obligations and deadlines, as written",
                         "paragraphs": [] if extract.get("commitments") else
                         ["No sentence stating an obligation or a deadline was found by the wording checks used."],
                         "bullets": extract.get("commitments") or []})
        if extract.get("dates") or extract.get("amounts"):
            sections.append({"heading": "Dates and amounts mentioned", "paragraphs": [],
                             "bullets": [f"Date: {d}" for d in extract.get("dates") or []]
                             + [f"Amount: {a}" for a in extract.get("amounts") or []]})
    sections.append({"heading": "How this was prepared",
                     "paragraphs": ["Prepared by the Desk from the file itself, by fixed rules. No model wrote or "
                                    "summarised any of it: figures are computed over every row, and sentences are "
                                    "quoted, not paraphrased. It is an extract to help you read the file, not a "
                                    "judgement of it."], "bullets": []})
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name)[:80]
    return {"title": f"Review of {name}", "filename": f"Review of {stem}.docx", "sections": sections}


def verify_generated(content: bytes, filename: str, expected: Mapping[str, Any]) -> Dict[str, Any]:
    """Open a file the Desk just created and check it is what was asked for:
    the right type, readable, with the title and headings (or sheets) that
    were approved. A file that merely exists is not verified."""
    found = read(filename, content)
    if not found["ok"]:
        return {"ok": False, "reason": found.get("code") or "file_not_accepted"}
    if not found["read"]:
        return {"ok": False, "reason": "generated_file_unreadable"}
    wanted_kind = expected.get("kind")
    if wanted_kind and found["kind"] != wanted_kind:
        return {"ok": False, "reason": "wrong_file_type", "found": found["kind"]}
    text = found["text"]
    missing = [str(h) for h in [expected.get("title"), *(expected.get("headings") or [])]
               if h and str(h).strip() and str(h).strip() not in text]
    if missing:
        return {"ok": False, "reason": "content_missing", "missing": missing[:5]}
    names = [s.get("name") for s in found["sheets"]]
    lost = [str(s) for s in expected.get("sheets") or [] if s not in names]
    if lost:
        return {"ok": False, "reason": "sheet_missing", "missing": lost[:5]}
    return {"ok": True, "reason": None, "found": {"kind": found["kind"], "sizeBytes": found["sizeBytes"],
                                                  "sha256": found["sha256"], "chars": found["chars"]}}
