"""Replay one reproduction against a running sandbox backend. Standard library
only; nothing from the lab is imported, so this file and a request file are
all that is needed.

    python replay.py --api http://127.0.0.1:8788 --request repro/1-RC-....json

It does what a person does in the product and nothing else: signs in as the
seeded development user, starts the case on the evaluation contract
(POST /desk/eval/v1/evaluation/runs), approves every action that is put in
front of it (or rejects, with --reject), and prints what the engine says at
the end. When the backend is the lab server it also prints the synthetic
office afterwards (GET /lab/v1/eval-runs/{id}/world).

It refuses a backend that does not report ``sandbox: true``. Sign-in uses the
seeded development user of Scriba's test backend; set AQL_EMAIL and
AQL_PASSWORD for another.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Optional, Tuple

ORIGIN = "http://localhost:5173"
EVAL = "/desk/eval/v1"


class Client:
    def __init__(self, root: str) -> None:
        self.root, self.cookie = root.rstrip("/"), ""

    def call(self, method: str, path: str, body: Any = None) -> Tuple[int, Any]:
        headers = {"Accept": "application/json", "Origin": ORIGIN, "X-Executive-Desk-Contract": "1.1.0"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        data = None
        if body is not None:
            data, headers["Content-Type"] = json.dumps(body).encode(), "application/json"
        request = urllib.request.Request(self.root + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw, status, cookies = response.read(), response.status, response.headers.get_all("Set-Cookie") or []
        except urllib.error.HTTPError as exc:
            raw, status, cookies = exc.read(), exc.code, []
        if path == "/auth/signin":
            self.cookie = "; ".join(c.split(";")[0].strip() for c in cookies)
        try:
            return status, json.loads(raw) if raw else None
        except ValueError:
            return status, raw[:300].decode("utf-8", "replace")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--api", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--reject", action="store_true", help="reject every approval instead of approving it")
    parser.add_argument("--json", action="store_true", help="print the result as JSON")
    args = parser.parse_args()
    with open(args.request, encoding="utf-8") as handle:
        request = json.load(handle)
    body = {key: request[key] for key in ("caseId", "input", "context", "mode")}

    client = Client(args.api)
    status, _ = client.call("POST", "/auth/signin", {"email": os.environ.get("AQL_EMAIL") or "alice@example.com",
                                                    "password": os.environ.get("AQL_PASSWORD") or "e2e-password-123"})
    if status != 200 or not client.cookie:
        print(f"sign-in failed (HTTP {status})", file=sys.stderr)
        return 2
    status, meta = client.call("GET", f"{EVAL}/meta")
    if status != 200 or not isinstance(meta, dict) or meta.get("sandbox") is not True:
        print("this backend does not report sandbox: true; nothing was sent", file=sys.stderr)
        return 2
    status, run = client.call("POST", f"{EVAL}/evaluation/runs", body)
    if status not in (200, 202) or not isinstance(run, dict):
        print(f"the case could not be started (HTTP {status}): {run}", file=sys.stderr)
        return 2
    run_id, decided, deadline = run["id"], [], time.monotonic() + 60
    while True:
        status, run = client.call("GET", f"{EVAL}/runs/{run_id}")
        state = (run or {}).get("status")
        if state == "awaiting_approval":
            _, listed = client.call("GET", f"{EVAL}/approvals?runId={run_id}")
            pending = [a for a in listed or [] if a.get("runId") == run_id and a.get("status") == "pending"]
            if not pending:
                break
            for approval in pending:
                decision = "reject" if args.reject else "approve"
                code, _ = client.call("POST", f"{EVAL}/approvals/{approval['id']}/decision",
                                      {"decision": decision, "decidedBy": "replay.py", "note": None})
                changes = approval.get("changes") or [{}]
                decided.append({"tool": changes[0].get("tool"), "decision": decision, "http": code,
                                "summary": approval.get("summary") or changes[0].get("summary")})
            continue
        if state in ("completed", "failed", "cancelled") or time.monotonic() > deadline:
            break
        time.sleep(0.2)

    lifecycle = run.get("lifecycle") if isinstance(run.get("lifecycle"), dict) else {"stage": run.get("lifecycle")}
    result = {
        "caseId": body["caseId"], "status": run.get("status"), "stage": lifecycle.get("stage"), "outcome": run.get("outcome"),
        "reason": lifecycle.get("reason"), "classification": (run.get("triage") or {}).get("classification"),
        "summary": run.get("summary"),
        "approvalsDecided": decided,
        "actions": [{"tool": a.get("tool"), "status": a.get("status")} for a in run.get("actions") or []],
        "office": None,
    }
    status, probe = client.call("GET", f"/lab/v1/eval-runs/{run_id}/world")
    if status == 200 and isinstance(probe, dict) and probe.get("world"):
        world = probe["world"]
        # Only what changed against the calendar the request carried.
        before = {e.get("id"): e for e in (body.get("context") or {}).get("calendar") or []}
        changed = []
        for e in world.get("events") or []:
            old = before.get(e.get("id"))
            row = {"id": e.get("id"), "title": e.get("title"), "start": e.get("start"), "end": e.get("end"),
                   "status": e.get("status"), "attendees": e.get("attendees")}
            if old is None:
                changed.append({"change": "CREATED", **row})
            elif (old.get("start"), old.get("end"), old.get("status") or "confirmed") != (e.get("start"), e.get("end"), e.get("status")):
                changed.append({"change": "CHANGED", "was": {"start": old.get("start"), "status": old.get("status")}, **row})
        result["office"] = {
            "calendarChanges": changed,
            "mailSent": [{"to": m.get("to"), "subject": m.get("subject"), "text": m.get("text")} for m in world.get("sent") or []],
            "tasks": [{"title": t.get("title"), "due": t.get("due_at"), "status": t.get("status")} for t in world.get("tasks") or []],
            "reminders": [{"title": r.get("title"), "at": r.get("remind_at") or r.get("due_at")} for r in world.get("reminders") or []],
            "followUps": [{"subject": f.get("subject"), "status": f.get("status")} for f in world.get("followUps") or []],
        }
    if args.json:
        print(json.dumps(result, indent=1, ensure_ascii=False, default=str))
        return 0
    print(f"case        {result['caseId']}")
    print(f"engine said status={result['status']} stage={result['stage']} outcome={result['outcome']} reason={result['reason']} "
          f"read as={result['classification']}")
    print(f"            \"{result['summary']}\"")
    for d in decided:
        print(f"approved    {d['tool']} ({d['decision']}, HTTP {d['http']})")
    for a in result["actions"]:
        print(f"action      {a['tool']}: {a['status']}")
    if result["office"] is None:
        print("office      not readable on this backend (no lab probe): the lines above are the engine's own account")
    else:
        empty = True
        for name in ("calendarChanges", "mailSent", "tasks", "reminders", "followUps"):
            for row in result["office"][name]:
                empty = False
                print(f"office      {name}: {json.dumps(row, ensure_ascii=False, default=str)}")
        if empty:
            print("office      nothing changed: no event created, moved or cancelled; no mail; no task, reminder or follow-up")
    return 0


if __name__ == "__main__":
    sys.exit(main())
