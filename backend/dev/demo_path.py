"""The autonomous path, end to end, over HTTP, with a real model and an isolated world.

mail arrives -> the worker picks it up -> the model reads it -> a checked plan -> a person approves
-> it executes in the sandbox -> it is verified by read-back -> a follow-up -> the run completes.

argv: base url, Scriba seed file. Nothing here can reach a real mailbox or calendar.
"""
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

import httpx

base, seed = sys.argv[1], Path(sys.argv[2]).read_text(encoding="utf-8")
password = re.search(r'ALICE_PASSWORD = "([^"]+)"', seed).group(1)
c = httpx.Client(base_url=base, headers={"Origin": "http://localhost:5173"}, timeout=120)
assert c.post("/auth/signin", json={"email": "alice@example.com", "password": password}).status_code == 200
health = c.get("/desk/health").json()
print("overlay", health.get("version"), "| external writes enabled:", health["externalWrites"]["enabled"],
      "| model:", json.dumps(health.get("model")))
world = c.get("/desk/sandbox").json()["world"]
now = dt.datetime.fromisoformat(world["now"])
print("sandbox world", world["id"], "| clock", world["now"])


def day(weekday):
    ahead = (weekday - now.weekday()) % 7 or 7
    return now.date() + dt.timedelta(days=ahead)


def wait_for_run(message_id, seconds=90):
    """The worker opens the run; this script never calls intake."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        for row in c.get("/desk/runs").json()["runs"]:
            if row.get("email_id") == message_id:
                return row
        time.sleep(3)
    raise SystemExit(f"the worker did not open a run for {message_id}")


def show(run, label):
    print(f"  [{label}] stage {run['lifecycle']['stage']}" + (f" ({run['lifecycle']['reason']})" if run["lifecycle"].get("reason") else ""),
          "| trigger", run["trigger"], "| planner", (run.get("plan") or {}).get("planner"))
    for a in run["actions"]:
        print(f"      {a['tool_name']:<22} {a.get('purpose') or '':<12} {a['status']:<18} lifecycle={a.get('lifecycle')} verified={a['verified']}"
              + (f" method={(a.get('verification') or {}).get('method')}" if a.get("verification") else ""))


def approve_all(run_id, rounds=6):
    run = c.get(f"/desk/runs/{run_id}").json()
    for _ in range(rounds):
        pending = [a for a in run["actions"] if a["status"] == "awaiting_approval"]
        if not pending:
            break
        for action in pending:
            result = c.post(action["approve"]["path"], json={}).json()["tool_call"]
            print(f"      approved {action['tool_name']} ({action.get('purpose')}) -> {result['status']}")
        run = c.get(f"/desk/runs/{run_id}").json()
    return run


# ── 1. one message, three things: a meeting, its confirmation, a promised document ──
# A time the Desk's own availability route reports free on every calendar.
free = c.get("/desk/availability", params={"start": (now + dt.timedelta(days=2)).isoformat(),
                                           "end": (now + dt.timedelta(days=7)).isoformat(),
                                           "duration_minutes": 45}).json()
slot = dt.datetime.fromisoformat(free["slots"][0]["start"])
before = slot.date() - dt.timedelta(days=1)
print("free slot chosen:", slot.isoformat(), "| zone", free.get("timezone"), "| complete", free.get("complete"))
body = (f"Hi,\n\nCould we meet on {slot.strftime('%A %d %B')} at {slot.strftime('%H:%M')} for 45 minutes to close the renewal? "
        f"Please also send me the signed price list by {before.strftime('%A')} noon so legal can check it first.\n\nThanks,\nNoor")
delivered = c.post("/desk/sandbox/deliver", json={"from_addr": "Noor Haddad <noor.haddad@atlasfreight.example>",
                                                  "subject": "Contract renewal", "body": body}).json()["delivered"]
print("\n1. delivered", delivered["id"], "(not taken in by this script: waiting for the worker)")
row = wait_for_run(delivered["id"])
run = c.get(f"/desk/runs/{row['runId']}").json()
show(run, "opened by the worker")
print("      intents:", [(i["type"], i.get("confidence"), i.get("source")) for i in run["plan"]["intents"]])
print("      steps:", [(s["id"], s["tool"], s["purpose"], s["state"], s["dependsOn"]) for s in run["plan"]["steps"]])
print("      usage:", json.dumps(run.get("usage"))[:200])
run = approve_all(run["runId"])
show(run, "after approvals")
print("      unresolved:", run.get("unresolved"), "| follow-ups:", [(f["id"], f["state"]) for f in run["followUps"]])

# ── 2. a time that is taken: times are offered, an answer is awaited, it arrives ──
busy = next((m for m in c.get("/desk/memory").json()["meetings"]["items"]
             if dt.datetime.fromisoformat(m["start"]) > now + dt.timedelta(hours=4)), None)
if busy is None:
    raise SystemExit("the demo world has no upcoming meeting to collide with")
start = dt.datetime.fromisoformat(busy["start"])
body = (f"Hello,\n\nCould we speak on {start.strftime('%A %d %B')} at {start.strftime('%H:%M')} "
        f"for 30 minutes about the Q1 volumes?\n\nBest,\nPetra")
delivered = c.post("/desk/sandbox/deliver", json={"from_addr": "Petra Lindholm <petra.lindholm@nordvik.example>",
                                                  "subject": "Q1 volumes", "body": body}).json()["delivered"]
print(f"\n2. delivered {delivered['id']}: asks for {busy['start']}, where \"{busy['title']}\" already is")
row = wait_for_run(delivered["id"])
run = c.get(f"/desk/runs/{row['runId']}").json()
show(run, "opened by the worker")
print("      held:", (run.get("held") or {}).get("reason"))
run = approve_all(run["runId"])
run = c.post(f"/desk/runs/{run['runId']}/advance").json()
show(run, "after the offer of times was approved")
print("      follow-ups:", [(f["id"], f["state"], f.get("waitingOn")) for f in run["followUps"]])
offered = next((a for a in run["actions"] if a.get("purpose") == "offer_times"), None)
slots = (offered or {}).get("proposedSlots") or []
answer = "Thanks. The first time you offered works for us." if not slots else \
    f"Thanks, {dt.datetime.fromisoformat(slots[0]['start']).strftime('%A at %H:%M')} works for us."
c.post("/desk/sandbox/deliver", json={"from_addr": "Petra Lindholm <petra.lindholm@nordvik.example>",
                                      "subject": "Re: Q1 volumes", "body": answer, "thread_id": delivered["threadId"]})
listing = c.get("/desk/follow-ups").json()
print("      after her answer arrived, follow-ups:", listing["counts"])
run = c.get(f"/desk/runs/{run['runId']}").json()
show(run, "the first run, once the awaited answer arrived")

ops = c.get("/desk/sandbox").json()["world"]
print("\nsandbox operations:", [(o["op"], o["status"]) for o in ops["operations"]][-12:])
print("isolation violations:", ops["isolationViolations"], "| external writes enabled:",
      c.get("/desk/health").json()["externalWrites"]["enabled"])
