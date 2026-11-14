"""A stable campaign: the same backend measured with independent seeds, and
only undisturbed runs kept.

    $PY tools/stable_campaign.py --api http://127.0.0.1:8811 --seeds 20270308,7,101,4242 --label <name>

Each seed regenerates the corpus (other senders, slots, greetings) and is a
full campaign of its own, written to ``reports/<label>-seed<N>/``.

A run is DISCARDED, and run again (once), when the machine was not running it
the whole time. That is measured, not guessed:

* a heartbeat thread reads the wall clock every second; a gap above
  ``--max-gap`` seconds between two beats means the process was suspended
  (machine sleep, hibernation, a frozen session);
* any case that ended as a lab ``error``, or whose wait for the engine timed
  out, means the timing was interrupted.

A discarded run keeps its report under ``reports/_scratch/`` with the reason;
it is never counted. The summary (``reports/<label>-seeds.json``) lists every
attempt, kept or not.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from aql.backend import BackendError, connect          # noqa: E402
from aql.campaign import FAMILIES, run_campaign, write_report   # noqa: E402


class Heartbeat:
    """The largest wall-clock gap between two one-second beats."""

    def __init__(self) -> None:
        self.max_gap = 0.0
        self.gaps: List[Dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._beat, daemon=True)

    def _beat(self) -> None:
        last = time.time()
        while not self._stop.wait(1.0):
            now = time.time()
            gap = now - last
            if gap > self.max_gap:
                self.max_gap = gap
            if gap > 5.0:
                self.gaps.append({"at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)), "seconds": round(gap, 1)})
            last = now

    def __enter__(self) -> "Heartbeat":
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._stop.set()
        self._thread.join(timeout=3)


def disturbance(report: Dict[str, Any], beat: Heartbeat, max_gap: float) -> List[str]:
    reasons = []
    if beat.max_gap > max_gap:
        reasons.append(f"the process was suspended: a {beat.max_gap:.0f} s gap in a one-second heartbeat")
    errors = [r["id"] for r in report["results"] if r["verdict"] == "error"]
    if errors:
        reasons.append(f"{len(errors)} cases ended as a lab error ({', '.join(errors[:4])})")
    timed_out = [r["id"] for r in report.get("_full") or [] if ((r.get("trace") or {}).get("stalled") or {}).get("timedOut")]
    if timed_out:
        reasons.append(f"{len(timed_out)} cases timed out waiting for the engine ({', '.join(timed_out[:4])})")
    return reasons


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--api", required=True)
    parser.add_argument("--seeds", required=True, help="comma-separated integers")
    parser.add_argument("--label", required=True)
    parser.add_argument("--max-gap", type=float, default=15.0)
    parser.add_argument("--families", default=",".join(FAMILIES))
    args = parser.parse_args()
    try:
        backend = connect(args.api)
    except BackendError as exc:
        print(f"Cannot use {args.api}: {exc.code}: {exc}", file=sys.stderr)
        return 2
    families = [f for f in args.families.split(",") if f]
    attempts: List[Dict[str, Any]] = []
    for seed in [int(s) for s in args.seeds.split(",") if s.strip()]:
        for attempt in (1, 2):
            label = f"{args.label}-seed{seed}"
            with Heartbeat() as beat:
                report = run_campaign(backend, seed=seed, families=families, label=label)
            reasons = disturbance(report, beat, args.max_gap)
            kept = not reasons
            out = HERE / "reports" / label if kept else HERE / "reports" / "_scratch" / f"{label}-discarded{attempt}"
            summary, gates = report["summary"], report["gates"]
            write_report(report, out)
            row = {"seed": seed, "attempt": attempt, "kept": kept, "discardedBecause": reasons, "report": str(out.relative_to(HERE)).replace("\\", "/"),
                   "backendCommit": report["traceability"]["backendCommit"], "executionMode": report["traceability"]["executionMode"],
                   "model": report["traceability"]["model"],
                   "startedAt": report["startedAt"], "finishedAt": report["finishedAt"],
                   "maxHeartbeatGapSeconds": round(beat.max_gap, 1), "heartbeatGaps": beat.gaps,
                   "items": summary["cases"], "byVerdict": summary["byVerdict"],
                   "completeJobSuccessRate": summary["completeJobSuccessRate"],
                   "safetyViolations": summary["safetyViolations"], "falseSuccesses": summary["falseSuccesses"],
                   "mandatoryApprovals": summary["mandatoryApprovals"], "humanRescues": summary["humanRescues"],
                   "hardGatesPassed": gates["hardGatesPassed"], "hardGatesFailed": gates["hardGatesFailed"],
                   "metamorphic": {k: report["metamorphic"][k] for k in ("relations", "hold", "broken")},
                   "rootCauses": {c["rootCause"]: c["affectedCases"] for c in report["rootCauses"]}}
            attempts.append(row)
            print(f"seed {seed} attempt {attempt}: {'KEPT' if kept else 'DISCARDED'} "
                  f"{summary['byVerdict']} false successes {summary['falseSuccesses']} "
                  f"gates {'pass' if gates['hardGatesPassed'] else 'FAIL ' + ','.join(gates['hardGatesFailed'])} "
                  f"max gap {beat.max_gap:.1f}s" + (f" :: {'; '.join(reasons)}" if reasons else ""), flush=True)
            (HERE / "reports" / f"{args.label}-seeds.json").write_text(json.dumps(
                {"format": "autonomy-quality-lab.stable-campaign/1", "label": args.label, "maxGapSeconds": args.max_gap,
                 "attempts": attempts}, indent=1), encoding="utf-8")
            if kept:
                break
    kept_rows = [a for a in attempts if a["kept"]]
    print(f"{len(kept_rows)} of {len({a['seed'] for a in attempts})} seeds kept; {len(attempts) - len(kept_rows)} runs discarded.")
    return 0 if all(a["hardGatesPassed"] for a in kept_rows) and kept_rows else 1


if __name__ == "__main__":
    sys.exit(main())
