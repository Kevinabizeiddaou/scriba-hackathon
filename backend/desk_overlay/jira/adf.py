"""Atlassian Document Format (ADF), both directions. Pure.

Jira Cloud's REST API v3 takes and returns rich text (an issue's description,
a comment, a worklog comment) as an ADF document, not as a string.

``to_adf`` turns what a person typed into a document Jira accepts:
paragraphs, bullet and numbered lists, headings, fenced code, quotes, links,
bold, inline code and mentions. A mention is written the way Jira's own wiki
markup writes it, ``[~accountid:<id>]``, so it can be produced by a picker and
never guessed from a display name.

``to_text`` reads a document back as plain text for a list row, a briefing
line or a model prompt. It covers every node Jira's editor produces; a node it
does not know contributes its text children, never an error.

Two rules the API enforces and that are easy to get wrong:

- a text node may not be empty (an empty document is a doc with no content);
- an unknown node or mark makes the whole request fail, so nothing outside
  this module builds ADF by hand.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Mapping, Optional

MAX_TEXT_CHARS = 30_000          # Jira's own limit on a comment or description is 32,767
_FENCE = "```"
_BULLET = re.compile(r"^\s*[-*•]\s+(.*)$")
_ORDERED = re.compile(r"^\s*(\d{1,3})[.)]\s+(.*)$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_QUOTE = re.compile(r"^>\s?(.*)$")
_RULE = re.compile(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$")
# One pass over a line: the first alternative that matches at a position wins.
_INLINE = re.compile(
    r"\[~accountid:(?P<mention>[A-Za-z0-9:_-]{1,128})\]"
    r"|`(?P<code>[^`\n]+)`"
    r"|\*\*(?P<bold>[^*\n]+)\*\*"
    r"|\[(?P<label>[^\]\n]{1,300})\]\((?P<href>https?://[^\s)]{1,2000})\)"
    r"|(?P<url>https?://[^\s<>\"']{1,2000})"
)
_TRAILING = ".,;:!?)"


def empty_document() -> Dict[str, Any]:
    return {"version": 1, "type": "doc", "content": []}


def _text(value: str, *marks: Dict[str, Any]) -> Dict[str, Any]:
    node: Dict[str, Any] = {"type": "text", "text": value}
    if marks:
        node["marks"] = list(marks)
    return node


def _inline(line: str, names: Mapping[str, str]) -> List[Dict[str, Any]]:
    """The inline nodes of one line. Never returns an empty text node."""
    nodes: List[Dict[str, Any]] = []
    position = 0
    for match in _INLINE.finditer(line):
        start, end = match.span()
        url = match.group("url")
        if url:
            # Punctuation that ends the sentence is not part of the address.
            trimmed = url.rstrip(_TRAILING)
            end = start + len(trimmed)
            url = trimmed
            if not url:
                continue
        if start > position:
            nodes.append(_text(line[position:start]))
        if match.group("mention"):
            account_id = match.group("mention")
            label = str(names.get(account_id) or "").strip().lstrip("@")
            attrs: Dict[str, Any] = {"id": account_id}
            if label:
                attrs["text"] = f"@{label}"
            nodes.append({"type": "mention", "attrs": attrs})
        elif match.group("code"):
            nodes.append(_text(match.group("code"), {"type": "code"}))
        elif match.group("bold"):
            nodes.append(_text(match.group("bold"), {"type": "strong"}))
        elif match.group("label"):
            nodes.append(_text(match.group("label"),
                               {"type": "link", "attrs": {"href": match.group("href")}}))
        elif url:
            nodes.append(_text(url, {"type": "link", "attrs": {"href": url}}))
        position = end
    if position < len(line):
        nodes.append(_text(line[position:]))
    return [node for node in nodes if node.get("type") != "text" or node.get("text")]


def _paragraph(lines: List[str], names: Mapping[str, str]) -> Dict[str, Any]:
    content: List[Dict[str, Any]] = []
    for index, line in enumerate(lines):
        if index:
            content.append({"type": "hardBreak"})
        content.extend(_inline(line.strip(), names))
    return {"type": "paragraph", "content": content}


def _list(kind: str, items: List[str], names: Mapping[str, str], order: int = 1) -> Dict[str, Any]:
    node: Dict[str, Any] = {
        "type": kind,
        "content": [{"type": "listItem", "content": [_paragraph([item], names)]} for item in items],
    }
    if kind == "orderedList" and order != 1:
        node["attrs"] = {"order": order}
    return node


def to_adf(text: Any, *, mention_names: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Plain text (with light markdown) to an ADF document.

    ``mention_names`` maps an Atlassian accountId to the display name shown
    for ``[~accountid:<id>]``. Jira resolves the mention from the id alone;
    the name is only what the reader sees before it does.
    """
    source = str(text or "").replace("\r\n", "\n").replace("\r", "\n")[:MAX_TEXT_CHARS]
    names = dict(mention_names or {})
    blocks: List[Dict[str, Any]] = []
    paragraph: List[str] = []
    bullets: List[str] = []
    numbered: List[str] = []
    first_number = 1
    quote: List[str] = []

    def flush() -> None:
        nonlocal paragraph, bullets, numbered, quote, first_number
        if paragraph:
            blocks.append(_paragraph(paragraph, names))
        if bullets:
            blocks.append(_list("bulletList", bullets, names))
        if numbered:
            blocks.append(_list("orderedList", numbered, names, first_number))
        if quote:
            blocks.append({"type": "blockquote", "content": [_paragraph(quote, names)]})
        paragraph, bullets, numbered, quote, first_number = [], [], [], [], 1

    lines = source.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if stripped.startswith(_FENCE):
            flush()
            language = stripped[len(_FENCE):].strip()
            body: List[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith(_FENCE):
                body.append(lines[index])
                index += 1
            index += 1                       # the closing fence, or the end of the text
            block: Dict[str, Any] = {"type": "codeBlock"}
            if re.fullmatch(r"[A-Za-z0-9+#_.-]{1,30}", language or ""):
                block["attrs"] = {"language": language.lower()}
            code = "\n".join(body)
            if code:
                block["content"] = [_text(code)]
            blocks.append(block)
            continue
        index += 1
        if not stripped:
            flush()
            continue
        if _RULE.match(line):
            flush()
            blocks.append({"type": "rule"})
            continue
        heading = _HEADING.match(stripped)
        if heading:
            flush()
            content = _inline(heading.group(2).strip(), names)
            if content:
                blocks.append({"type": "heading", "attrs": {"level": len(heading.group(1))},
                               "content": content})
            continue
        bullet, ordered, quoted = _BULLET.match(line), _ORDERED.match(line), _QUOTE.match(stripped)
        if bullet and bullet.group(1).strip():
            if paragraph or numbered or quote:
                flush()
            bullets.append(bullet.group(1).strip())
        elif ordered and ordered.group(2).strip():
            if paragraph or bullets or quote:
                flush()
            if not numbered:
                first_number = int(ordered.group(1))
            numbered.append(ordered.group(2).strip())
        elif quoted is not None and stripped.startswith(">"):
            if paragraph or bullets or numbered:
                flush()
            if quoted.group(1).strip():
                quote.append(quoted.group(1))
        else:
            if bullets or numbered or quote:
                flush()
            paragraph.append(line)
    flush()
    return {"version": 1, "type": "doc", "content": blocks}


def is_empty(document: Any) -> bool:
    return not to_text(document).strip()


# ── reading ────────────────────────────────────────────────────────────────

_BLOCKS = {"paragraph", "heading", "blockquote", "panel", "expand", "nestedExpand", "listItem",
           "taskItem", "decisionItem", "tableCell", "tableHeader", "layoutColumn", "caption"}


def _children(node: Mapping[str, Any]) -> List[Any]:
    content = node.get("content")
    return content if isinstance(content, list) else []


def _inline_text(node: Mapping[str, Any]) -> str:
    return "".join(_render(child, 0) for child in _children(node))


def _render(node: Any, depth: int) -> str:
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return "\n".join(part for part in (_render(item, depth) for item in node) if part.strip())
    if not isinstance(node, Mapping):
        return str(node)
    kind = str(node.get("type") or "")
    attrs = node.get("attrs") if isinstance(node.get("attrs"), Mapping) else {}

    if kind == "text":
        return str(node.get("text") or "")
    if kind == "hardBreak":
        return "\n"
    if kind == "mention":
        label = str(attrs.get("text") or "").strip()
        return label if label else "@someone"
    if kind == "emoji":
        return str(attrs.get("text") or attrs.get("shortName") or "")
    if kind in ("inlineCard", "blockCard", "embedCard"):
        return str(attrs.get("url") or "")
    if kind == "date":
        return _date(attrs.get("timestamp"))
    if kind == "status":
        return f"[{attrs.get('text')}]" if attrs.get("text") else ""
    if kind in ("media", "mediaInline"):
        return f"[attachment: {attrs.get('alt')}]" if attrs.get("alt") else "[attachment]"
    if kind == "rule":
        return "---"
    if kind == "codeBlock":
        return _inline_text(node)
    if kind in ("bulletList", "orderedList", "taskList", "decisionList"):
        start = int(attrs.get("order") or 1) if kind == "orderedList" else 1
        lines: List[str] = []
        for offset, item in enumerate(_children(node)):
            marker = f"{start + offset}." if kind == "orderedList" else "-"
            body = _render(item, depth + 1).strip()
            if not body:
                continue
            first, *rest = body.split("\n")
            lines.append(f"{'  ' * depth}{marker} {first}")
            lines.extend(rest)
        return "\n".join(lines)
    if kind == "table":
        return "\n".join(part for part in (_render(row, depth) for row in _children(node)) if part)
    if kind == "tableRow":
        return " | ".join(_render(cell, depth).replace("\n", " ").strip() for cell in _children(node))
    if kind in ("listItem", "taskItem", "decisionItem"):
        parts = [_render(child, depth) for child in _children(node)]
        return "\n".join(part for part in parts if part.strip())
    if kind in ("paragraph", "heading", "caption") or (kind in _BLOCKS and not _has_block(node)):
        return _inline_text(node)
    parts = [_render(child, depth) for child in _children(node)]
    joined = "\n".join(part for part in parts if part.strip())
    return joined or str(node.get("text") or "")


def _has_block(node: Mapping[str, Any]) -> bool:
    return any(isinstance(child, Mapping) and child.get("type") != "text" and _children(child)
               for child in _children(node))


def _date(timestamp: Any) -> str:
    import datetime as dt

    try:
        return dt.datetime.fromtimestamp(int(timestamp) / 1000, dt.timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def to_text(document: Any) -> str:
    """A document as plain text. A string (API v2, or a webhook payload) is returned as it is."""
    if isinstance(document, str):
        return document.strip()
    if not isinstance(document, Mapping):
        return ""
    blocks = [_render(child, 0) for child in _children(document)] \
        if document.get("type") == "doc" else [_render(document, 0)]
    return "\n\n".join(block for block in blocks if block.strip()).strip()


def excerpt(document: Any, limit: int = 280) -> str:
    """One line of a document, for a list row."""
    text = re.sub(r"\s+", " ", to_text(document)).strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def mentioned_account_ids(document: Any) -> List[str]:
    """Every accountId mentioned in a document, in order, without repeats."""
    found: List[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, Mapping):
            if node.get("type") == "mention":
                account_id = str((node.get("attrs") or {}).get("id") or "").strip()
                if account_id and account_id not in found:
                    found.append(account_id)
            walk(node.get("content"))

    walk(document)
    return found


def mention_tokens(account_ids: Iterable[str]) -> str:
    """The text form of mentions, to prepend to something a person typed."""
    return " ".join(f"[~accountid:{account_id}]" for account_id in account_ids if account_id)
