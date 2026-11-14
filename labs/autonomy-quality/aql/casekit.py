"""Small builders shared by the metamorphic and adversarial campaigns."""
from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from . import office as o
from .model import stable_hash


def make(case_id: str, family: str, category: str, sender: str, subject: str, body: str, *,
         intents: List[str], jobs: Optional[List[Dict[str, Any]]] = None,
         any_of: Optional[List[List[Dict[str, Any]]]] = None, tags: Optional[List[str]] = None,
         thread: Optional[List[Dict[str, Any]]] = None, ctx: Optional[Dict[str, Any]] = None, policy: Any = None,
         allowed: Optional[List[str]] = None, truth: Optional[Dict[str, Any]] = None, title: str = "",
         script: Optional[List[Dict[str, Any]]] = None, extra: Optional[List[Dict[str, Any]]] = None,
         seed: Optional[int] = None, lang: str = "en", sender_person: Optional[Dict[str, str]] = None,
         cc: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    message = o.mail(f"m-{case_id.lower().replace('/', '-')}", sender, subject, body, cc=cc)
    if sender_person:
        message["from"] = dict(sender_person)
    for earlier in thread or []:
        earlier["threadId"] = message["threadId"]
    requester = (sender_person or {}).get("email") or o.addr(sender)
    the_truth: Dict[str, Any] = {"intents": intents, "requester": requester,
                                 "allowedRecipients": [o.addr(a) if a in o.P else a for a in (allowed or [])]}
    if any_of is not None:
        the_truth["anyOf"] = any_of
    else:
        the_truth["jobs"] = jobs or [{"kind": "none"}]
    the_truth.update(truth or {})
    case: Dict[str, Any] = {
        "id": case_id, "family": family, "category": category, "title": title or subject, "tags": sorted(set(tags or [])),
        "lang": lang, "seed": seed, "input": {"kind": "email", "email": message, "thread": thread or []},
        "context": o.context(**(ctx or {})), "policy": policy or "approve_all", "truth": the_truth}
    if script:
        case["script"] = script
    if extra:
        case["extraChecks"] = extra
    case["hash"] = stable_hash({"input": case["input"], "context": case["context"], "truth": case["truth"],
                                "script": case.get("script"), "policy": case["policy"]})
    return case


def derive(base: Dict[str, Any], case_id: str, **changes: Any) -> Dict[str, Any]:
    """A copy of a case with some parts replaced. ``body``/``subject`` replace
    the message text; ``context``, ``truth``, ``policy``, ``script``,
    ``extraChecks``, ``thread`` replace or (for dicts) update the part."""
    case = copy.deepcopy(base)
    case["id"] = case_id
    email = case["input"]["email"]
    email["id"] = f"m-{case_id.lower().replace('/', '-')}"
    old_thread = email["threadId"]
    email["threadId"] = f"thr-{email['id']}"
    for earlier in case["input"].get("thread") or []:
        if earlier.get("threadId") == old_thread:
            earlier["threadId"] = email["threadId"]
    for key, value in changes.items():
        if key in ("body", "bodyText"):
            email["bodyText"] = value
        elif key == "subject":
            email["subject"] = value
        elif key == "sender":
            email["from"] = dict(o.P[value])
            case["truth"]["requester"] = o.addr(value)
        elif key == "thread":
            for earlier in value:
                earlier["threadId"] = email["threadId"]
            case["input"]["thread"] = value
        elif key in ("truth", "context") and isinstance(value, dict):
            case[key].update(value)
        else:
            case[key] = value
    case["parent"] = base["id"]
    case["hash"] = stable_hash({"input": case["input"], "context": case["context"], "truth": case["truth"],
                                "script": case.get("script"), "policy": case["policy"]})
    return case


def earlier(message_id: str, sender: str, subject: str, body: str, when: str) -> Dict[str, Any]:
    return o.mail(message_id, sender, subject, body, sent_at=when)


OUTSIDER = "victor.lang@quickdeal-partners.example"
