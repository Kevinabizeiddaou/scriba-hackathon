"""Plant one defect at a time in a safety guard and check the suite notices."""
import os
import subprocess
import sys
from pathlib import Path

backend = Path(sys.argv[1])
scriba = sys.argv[2]
UNIT = ["tests", "--ignore=tests/integration"]
ALL = ["tests"]

MUTANTS = [
    ("gate: external writes not held", "desk_overlay/execution.py",
     "if tool in readiness.EXTERNAL_WRITE_TOOLS and world is None and not gate.writes_enabled():",
     "if False:", ALL),
    ("gate: executor does not fail closed either", "desk_overlay/execution.py",
     "if ctx is not None and kind in readiness.EXTERNAL_WRITE_TOOLS and not gate.writes_enabled():",
     "if False:", ALL),
    ("gate: tripwire does not raise", "desk_overlay/execution.py",
     "            if world is not None:\n                world.violations.append(label)",
     "            if False:\n                world.violations.append(label)", ALL),
    ("gate: unknown outcome reported as plain failure", "desk_overlay/execution.py",
     'outcome_unknown = ctx["notes"].get("outcome") == "unknown" and status == "failed"',
     "outcome_unknown = False", ALL),
    ("gate: unknown outcome retried without a read-back", "desk_overlay/execution.py",
     "                settled = gate._reconcile(ctx, tool, overrides, hold)", "                settled = None", ALL),
    ("gate: a gone sandbox falls through", "desk_overlay/execution.py",
     '                raise LookupError("sandbox_world_gone")', "                return None", ALL),
    ("readiness: env alone enables writes", "desk_overlay/readiness.py",
     "    verified = bool(commit) and any(", "    verified = True or any(", UNIT),
    ("readiness: lead switch not required", "desk_overlay/readiness.py",
     '{"id": "lead_authorization", "ok": bool(lead) and _on(env.get(ENV_SWITCH)),',
     '{"id": "lead_authorization", "ok": True,', UNIT),
    ("claims: memory store hands out a held key", "desk_overlay/claims.py",
     '            if row is None or row["status"] == "failed":', "            if True:", UNIT),
    ("workflow: in-flight claim not respected", "desk_overlay/workflow.py",
     "            if not claim.claimed:\n                raise IntakeBusy", "            if False:\n                raise IntakeBusy", UNIT),
    ("workflow: injection not held", "desk_overlay/workflow.py",
     "        if planning.injection_suspected(item.get(\"subject\"), text):", "        if False:", UNIT),
    ("workflow: busy time booked anyway", "desk_overlay/workflow.py",
     '        if check["free"] is not True:\n            conflict = check["free"] is False\n            self._hold(\n                plan, user, item, calendar,\n                "calendar_conflict"',
     '        if False:\n            conflict = check["free"] is False\n            self._hold(\n                plan, user, item, calendar,\n                "calendar_conflict"', UNIT),
    ("workflow: non-organizer change proposed", "desk_overlay/workflow.py",
     '        if not event.get("is_organizer"):', "        if False:", UNIT),
    ("workflow: stranger's change request acted on", "desk_overlay/planning.py",
     "        if sender and sender in people:", "        if True:", UNIT),
    ("workflow: overdue follow-up sends repeated reminders", "desk_overlay/workflow.py",
     'if follow.get("state") == "waiting" and due is not None and now > due:',
     'if due is not None and now > due:', UNIT),
    ("workflow: unreadable mailbox treated as no answer", "desk_overlay/workflow.py",
     '        if not all(source.get("ok") for source in sources):\n            return',
     '        if False:\n            return', UNIT),
    ("workflow: partial counted as verified", "desk_overlay/workflow.py",
     '        verified = bool(verification.get("verified")) and status in _DONE\n    else:\n        verified = bool(status in _DONE and card.get("assistant_action_id"))',
     '        verified = bool(verification.get("verified"))\n    else:\n        verified = bool(card.get("assistant_action_id"))', UNIT),
    ("worker: starts in production", "desk_overlay/worker.py",
     "        if self.gateway.is_production():", "        if False:", UNIT),
    ("worker: overlapping ticks allowed", "desk_overlay/worker.py",
     "        if not self._tick_lock.acquire(blocking=False):", "        if False and not self._tick_lock.acquire(blocking=False):", UNIT),
    ("worker: hourly limit ignored", "desk_overlay/worker.py",
     "budget = min(self.max_new, self.max_per_hour - len(slot[\"openedAt\"]))", "budget = self.max_new", UNIT),
    ("agent: any tool allowed", "desk_overlay/agent.py",
     "                if name not in READ_TOOLS:", "                if False:", UNIT),
    ("agent: step limit removed", "desk_overlay/agent.py",
     "            for _ in range(MAX_STEPS):", "            for _ in range(50):", UNIT),
    ("agent: proposal type not checked", "desk_overlay/agent.py",
     "            if kind not in PROPOSAL_TYPES:\n                reason = \"type_not_allowed\"\n            elif kind == \"reply\":",
     "            if kind == \"reply\":", UNIT),
    ("sandbox: default world answers for anyone", "desk_overlay/sandbox.py",
     '        return self._defaults.get(str(email or "").strip().lower())',
     "        return next(iter(self._defaults.values()), None)", UNIT),
    ("sandbox: organizer not required for a change", "desk_overlay/sandbox.py",
     '            if event["organizer"] not in self.own_addresses():', "            if False:", UNIT),
    ("sandbox: same event created twice", "desk_overlay/sandbox.py",
     '                if (existing["status"] != "cancelled" and existing["provider"] == provider',
     '                if (False and existing["provider"] == provider', UNIT),
    ("eval: another user's run visible", "desk_overlay/eval_api.py",
     '        if record is None or record["user"].id != user.id:', "        if record is None:", ALL),
    ("eval: contradicting decision accepted", "desk_overlay/eval_api.py",
     '            if current["status"] != "pending":\n                raise EvalError(409',
     '            if False:\n                raise EvalError(409', ALL),
    ("gateway: placeholder key treated as a model", "desk_overlay/gateway.py",
     '        if placeholder and not os.environ.get("OPENAI_BASE_URL", "").strip():\n            return False',
     '        if False:\n            return False', ALL),
    ("reading: ambiguous zone converted anyway", "desk_overlay/reading.py",
     "    if _AMBIGUOUS_ZONE.search(raw):\n        return None, True", "    if False:\n        return None, True", UNIT),
]

env = dict(os.environ, SCRIBA_BACKEND_PATH=scriba)
caught, missed, broken = [], [], []
import os as _os
ONLY = _os.environ.get('ONLY')
for name, rel, old, new, scope in MUTANTS:
    if ONLY and not any(k in name for k in ONLY.split('|')):
        continue
    path = backend / rel
    original = path.read_text(encoding="utf-8")
    if original.count(old) != 1:
        broken.append(f"{name}: anchor found {original.count(old)} times")
        continue
    path.write_text(original.replace(old, new), encoding="utf-8")
    try:
        result = subprocess.run([sys.executable, "-m", "pytest", *scope, "-q", "-x", "-p", "no:logging",
                                 "-W", "ignore", "--tb=no", "-p", "no:cacheprovider"],
                                cwd=backend, env=env, capture_output=True, text=True, timeout=420)
        (caught if result.returncode != 0 else missed).append(name)
    except subprocess.TimeoutExpired:
        caught.append(name + " (hung: counted as noticed)")
    finally:
        path.write_text(original, encoding="utf-8")
    print(("CAUGHT " if name in caught or any(c.startswith(name) for c in caught) else "MISSED ") + name, flush=True)
print(f"\n{len(caught)} caught, {len(missed)} missed, {len(broken)} not applied")
for line in missed:
    print("  MISSED:", line)
for line in broken:
    print("  NOT APPLIED:", line)
