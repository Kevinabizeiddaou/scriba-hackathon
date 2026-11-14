"""The documents quote the evidence; this keeps them from drifting apart,
and keeps anything that says where it was run out of the committed files."""
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE, DOCS = ROOT / "evidence", ROOT / "docs"


def load(name):
    path = EVIDENCE / name
    if not path.is_file():
        pytest.skip(f"{name} has not been generated (python -m officesim run all)")
    return json.loads(path.read_text(encoding="utf-8"))


def text(name):
    return (DOCS / name).read_text(encoding="utf-8")


def test_submission_pack_quotes_the_measured_numbers():
    c = load("all-profiles.json")["combined"]
    t = load("all-profiles-trusting.json")["combined"]
    r = load("robustness/robustness.json")["counts"]
    pack = text("SUBMISSION_EVIDENCE.md")
    rate = f"{c['handledWithApprovalsOnly'] / c['actionable']:.0%}"
    for wanted in (
        f"receives {c['requestsReceived']} messages",
        f"of which {c['actionable']} need work",
        f"**Handled with approvals only: {c['handledWithApprovalsOnly']} of {c['actionable']} actionable requests ({rate}).**",
        f"| Requests completed correctly | {c['completedCorrectly']} of {c['actionable']} |",
        f"| Requests correctly handed to the executive | {c['correctlyHandedToExecutive']} |",
        f"| Calendar changes (created, moved, cancelled) | {c['calendarChangesVerified']} |",
        f"| Email replies (confirmations and offers of times) | {c['emailRepliesVerified']} |",
        f"| Tasks | {c['tasksAndRemindersVerified']} |",
        f"| Follow-ups satisfied | {c['followUpsSatisfied']} |",
        f"| Duplicates prevented | {c['duplicatesPrevented']} |",
        f"| Approval of a correct proposal | {c['mandatoryApprovals']} | No |",
        f"| Rejection for her own reasons | {c['preferenceRejections']} | No |",
        f"| Edit for her own reasons | {c['preferenceEdits']} | No |",
        f"| Wrong proposal stopped (manual rescue) | {c['manualRescues']} | Yes |",
        f"| Proposal corrected at approval | {c['manualCorrections']} | Yes |",
        f"| Incomplete proposal completed by hand | {c['missingInformationSupplied']} | Yes |",
        f"| Retry after a provider failure | {c['recoveryRetries']} | Counted separately |",
        f"| Requests left for a human to do | {c['leftForHuman']} of {c['actionable']} | Yes |",
        f"{t['incorrect']}\nrequests ended with something wrong in the world, against {c['incorrect']} when she reads",
        f"{r['pass']} robustness cases passed, {r['FAIL']} failed, {r['NOT RUN']} could not be run",
        f"there were {c['mandatoryApprovals']} approvals of correct\nproposals",
    ):
        assert wanted in pack, f"SUBMISSION_EVIDENCE.md no longer matches the evidence: {wanted!r}"
    assert c["invariantViolations"] == 0 and t["invariantViolations"] == 0
    assert c["incorrect"] == 0


def test_storyboard_and_differentiation_quote_the_measured_numbers():
    c = load("all-profiles.json")["combined"]
    line = (f"{c['actionable']} actionable requests; {c['handledWithApprovalsOnly']} handled with\n"
            f"approvals only; {c['incorrect']} incorrect; {c['manualRescues']} wrong proposals stopped; "
            f"{c['leftForHuman']} left for a human.")
    assert line in text("DEMO_STORYBOARD.md")
    assert f"{c['handledWithApprovalsOnly']} of {c['actionable']} requests that needed work" in text("DIFFERENTIATION.md")
    assert f"({c['followUpsSatisfied']} satisfied)" in text("DIFFERENTIATION.md")
    assert "No video has been recorded" in text("DEMO_STORYBOARD.md")


def test_every_run_in_the_evidence_was_started_by_the_worker_and_is_simulated():
    load("all-profiles.json")
    for runs_file in EVIDENCE.glob("*/runs.json"):
        for run in json.loads(runs_file.read_text(encoding="utf-8")).values():
            assert run["trigger"] == "worker", (runs_file.parent.name, run["runId"])
            assert run["simulated"] is True


def test_screenshots_named_in_the_storyboard_exist():
    shots = EVIDENCE / "demo" / "screenshots"
    if not shots.is_dir():
        pytest.skip("no screenshots were captured (python -m officesim demo --browser)")
    for name in re.findall(r"`(\d\d-[\w-]+\.png)`", text("DEMO_STORYBOARD.md")):
        assert (shots / name).is_file(), name


def test_nothing_committed_says_where_it_was_run_or_names_a_real_address():
    """No local path, no user name, and only reserved example domains."""
    address = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
    local = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]|/Users/[a-z]|/home/[a-z]")
    for folder in (EVIDENCE, DOCS, ROOT / "officesim", ROOT / "browser", ROOT / "tests"):
        for path in folder.rglob("*"):
            if path.suffix not in (".json", ".jsonl", ".md", ".py", ".mjs") or "node_modules" in path.parts:
                continue
            body = path.read_text(encoding="utf-8", errors="replace")
            if path.name != "test_docs.py":
                assert not local.search(body), f"{path.relative_to(ROOT)} contains a local path"
            for domain in address.findall(body):
                domain = domain.lower().rstrip(".")
                assert domain.endswith(".example") or domain in ("example.com", "anthropic.com"), \
                    f"{path.relative_to(ROOT)} names an address at {domain}"
