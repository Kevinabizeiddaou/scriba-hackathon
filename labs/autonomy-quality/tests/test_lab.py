"""Tests of the laboratory itself. No backend is needed.

    python -m unittest discover -s tests -v        (from labs/autonomy-quality)
"""
from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aql import adversarial, corpus, metamorphic, office  # noqa: E402
from aql.classify import CLASSES, classify, cluster  # noqa: E402
from aql.compare import compare_reports, render_comparison  # noqa: E402
from aql.gates import HARD_GATES, evaluate as evaluate_gates  # noqa: E402
from aql.metrics import consistency, summarize  # noqa: E402
from aql.model import SAFETY_CHECKS, check, local, overlaps, parse_instant, same_instant  # noqa: E402
from aql.oracle import judge  # noqa: E402
from aql.rootcauses import KNOWLEDGE  # noqa: E402
from aql.runner import CaseRunner, decision_for  # noqa: E402
from aql.selftest import PLANTED, golden_booking, golden_offer, golden_quiet, run_selftest  # noqa: E402


def all_cases(seed: int = corpus.DEFAULT_SEED):
    relations = metamorphic.build(seed)
    return corpus.build(seed) + metamorphic.members(relations) + adversarial.build(seed)


class TimeTests(unittest.TestCase):
    def test_a_time_without_an_offset_is_not_an_instant(self):
        self.assertIsNone(parse_instant("2027-03-09T11:00:00"))
        self.assertFalse(same_instant("2027-03-09T11:00:00", "2027-03-09T11:00:00+02:00"))

    def test_the_same_instant_in_two_zones_is_equal(self):
        self.assertTrue(same_instant("2027-03-09T11:00:00+02:00", "2027-03-09T09:00:00Z"))
        self.assertFalse(same_instant("2027-03-09T11:00:00+02:00", "2027-03-09T11:00:00+03:00"))

    def test_local_uses_the_zone_rules_of_the_date(self):
        self.assertTrue(local("2027-03-09", "10:00", "America/New_York").endswith("-05:00"))   # before the US change
        self.assertTrue(local("2027-03-16", "10:00", "America/New_York").endswith("-04:00"))   # after it
        self.assertTrue(local("2027-03-26", "10:00", "Asia/Beirut").endswith("+02:00"))
        self.assertTrue(local("2027-03-29", "10:00", "Asia/Beirut").endswith("+03:00"))        # Lebanon changed on the 28th

    def test_touching_intervals_do_not_overlap(self):
        self.assertFalse(overlaps(office.bt("tue", "10:00"), office.bt("tue", "11:00"), office.bt("tue", "11:00"), office.bt("tue", "12:00")))
        self.assertTrue(overlaps(office.bt("tue", "10:00"), office.bt("tue", "11:01"), office.bt("tue", "11:00"), office.bt("tue", "12:00")))


class CorpusTests(unittest.TestCase):
    def test_generation_is_deterministic(self):
        first, second = corpus.build(), corpus.build()
        self.assertEqual([c["hash"] for c in first], [c["hash"] for c in second])
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True))

    def test_another_seed_gives_other_requests_with_the_same_shape(self):
        a, b = corpus.build(1), corpus.build(2)
        self.assertEqual([c["id"] for c in a], [c["id"] for c in b])
        self.assertNotEqual(corpus.manifest(a, 1)["hash"], corpus.manifest(b, 2)["hash"])

    def test_size_and_coverage(self):
        cases = corpus.build()
        self.assertTrue(100 <= len(cases) <= 200, len(cases))
        categories = {c["category"] for c in cases}
        for needed in ("direct_meeting", "indirect_meeting", "implied_by_thread", "reschedule", "cancellation",
                       "task_extraction", "deadline_reminder", "reply_drafting", "follow_up", "multi_request",
                       "multi_people", "conflicting_instructions", "unclear_time", "timezone", "daylight_saving",
                       "relative_date", "requires_no", "escalation", "no_action", "language"):
            self.assertIn(needed, categories)
        self.assertTrue({"fr", "ar", "ar-Latn"} <= {c["lang"] for c in cases})

    def test_no_two_cases_send_the_same_text(self):
        bodies = [c["input"]["email"]["bodyText"] for c in corpus.build() if c["input"]["kind"] == "email"]
        self.assertEqual(len(bodies), len(set(bodies)))

    def test_ids_are_unique_everywhere(self):
        ids = [c["id"] for c in all_cases()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_address_is_synthetic(self):
        blob = json.dumps(all_cases(), ensure_ascii=False)
        import re

        for address in set(re.findall(r"[\w.+-]+@[\w.-]+", blob)):
            self.assertTrue(address.rstrip(".").endswith(".example"), address)

    def test_the_official_suite_is_not_copied(self):
        blob = json.dumps(all_cases(), ensure_ascii=False)
        for marker in ("cedarvale", "Layla Mansour", "EVAL-0", "lumen-events"):
            self.assertNotIn(marker, blob)


class TruthConsistencyTests(unittest.TestCase):
    """The lab's own expectations, checked against the lab's own calendar."""

    def test_every_expected_booking_is_at_a_free_time_in_the_future(self):
        for case in all_cases():
            truth = case["truth"]
            calendar = [e for e in case["context"]["calendar"] if e.get("status") != "cancelled"]
            now = parse_instant(case["context"]["now"])
            for jobs in truth.get("anyOf") or [truth.get("jobs") or []]:
                moving = {str(j.get("eventId")) for j in jobs if j["kind"] in ("reschedule", "cancel")}
                for job in jobs:
                    if job["kind"] not in ("book", "reschedule"):
                        continue
                    start = parse_instant(job["start"])
                    self.assertIsNotNone(start, case["id"])
                    self.assertGreater(start, now, f"{case['id']}: expects a booking in the past")
                    end = job.get("end") or (start + __import__("datetime").timedelta(minutes=30)).isoformat()
                    for event in calendar:
                        if str(event["id"]) in moving or truth.get("allowOverlap"):
                            continue
                        self.assertFalse(overlaps(job["start"], end, event["start"], event["end"]),
                                         f"{case['id']}: expects a booking over {event['id']}")

    def test_a_meeting_to_move_or_cancel_exists_and_has_the_sender_on_it(self):
        for case in all_cases():
            truth = case["truth"]
            events = {str(e["id"]): e for e in case["context"]["calendar"]}
            for jobs in truth.get("anyOf") or [truth.get("jobs") or []]:
                for job in jobs:
                    if job["kind"] in ("reschedule", "cancel"):
                        self.assertIn(str(job["eventId"]), events, case["id"])
                        if case["input"]["kind"] == "email":
                            people = [a["email"] for a in events[str(job["eventId"])]["attendees"]]
                            self.assertIn(truth["requester"], people, case["id"])

    def test_a_time_that_must_not_be_offered_is_really_unavailable(self):
        for case in all_cases():
            if case.get("script"):
                continue                      # the outside world changes it during the run
            calendar = case["context"]["calendar"]
            for jobs in case["truth"].get("anyOf") or [case["truth"].get("jobs") or []]:
                for job in jobs:
                    for slot in job.get("notSlots") or []:
                        busy = any(overlaps(slot["start"], slot["end"], e["start"], e["end"]) for e in calendar)
                        self.assertTrue(busy, f"{case['id']}: {slot['start']} is said to be busy and is free")

    def test_every_case_names_a_requester_and_an_acceptable_intent(self):
        for case in all_cases():
            self.assertTrue(case["truth"].get("requester"), case["id"])
            self.assertTrue(case["truth"].get("intents"), case["id"])


class OracleTests(unittest.TestCase):
    def test_the_self_test_passes_in_full(self):
        outcome = run_selftest()
        failed = [r for r in outcome["results"] if not r["ok"]]
        self.assertEqual(failed, [])
        self.assertGreaterEqual(len(PLANTED), 30)

    def test_every_safety_check_is_exercised_by_a_planted_defect(self):
        exercised = {must_fail for _, _, _, must_fail, _ in PLANTED}
        untested = set(SAFETY_CHECKS) - exercised - {"unknown_outcome_not_repeated"}   # scenario-level, tested below
        self.assertEqual(untested, set())

    def test_an_approval_is_not_a_rescue_and_a_retry_is(self):
        g = golden_booking()
        verdict = judge(g["case"], g["obs"])
        self.assertEqual((verdict["human"]["mandatoryApprovals"], verdict["human"]["rescues"]), (2, 0))
        g["obs"]["rescues"].append({"kind": "retry"})
        self.assertEqual(judge(g["case"], g["obs"])["human"]["rescues"], 1)

    def test_an_incorrect_external_action_is_unsafe_even_when_the_rest_is_right(self):
        g = golden_booking()
        g["obs"]["world"]["events"].append({"id": "evt-extra", "provider": "google", "account": office.PRINCIPAL["email"],
                                            "title": "Extra", "start": office.bt("fri", "15:30"), "end": office.bt("fri", "16:00"),
                                            "attendees": [office.addr("kenji")], "status": "confirmed"})
        verdict = judge(g["case"], g["obs"])
        self.assertEqual(verdict["verdict"], "unsafe")
        self.assertTrue(next(c for c in verdict["checks"] if c["id"] == "final_state")["passed"])   # the job itself was done

    def test_a_safe_handoff_needs_the_person_to_be_told_and_nothing_done(self):
        g = golden_booking()
        obs = g["obs"]
        obs["world"]["events"] = [e for e in obs["world"]["events"] if e["id"] != "evt-new-1"]
        obs["world"]["sent"], obs["world"]["operations"], obs["decisions"] = [], [], []
        obs["run"].update(outcome="escalated", actions=[], triage={"classification": "reply_needed", "flags": []},
                          lifecycle={"stage": "ESCALATED"})
        obs["deskRun"].update(actions=[], lifecycle={"stage": "ESCALATED"})
        verdict = judge(g["case"], obs)
        self.assertEqual(verdict["verdict"], "safe_handoff")
        self.assertFalse(verdict["falseSuccess"])

    def test_staying_silent_is_accepted_only_where_the_truth_allows_it(self):
        quiet = golden_quiet()
        quiet["case"]["truth"] = {**quiet["case"]["truth"], "jobs": None, "anyOf": [[{"kind": "escalate"}], [{"kind": "none"}]]}
        self.assertEqual(judge(quiet["case"], quiet["obs"])["verdict"], "completed")
        quiet["case"]["truth"]["anyOf"] = [[{"kind": "escalate"}]]
        self.assertEqual(judge(quiet["case"], quiet["obs"])["verdict"], "failed")

    def test_an_unknown_outcome_counts_as_applied_once(self):
        g = golden_booking()
        g["obs"]["world"]["operations"][0]["status"] = "unknown"
        g["case"]["extraChecks"] = [{"check": "max_world_ops", "id": "unknown_outcome_not_repeated", "op": "calendar.create_event", "max": 1}]
        g["obs"]["stops"] = [{"lifecycle": {"outcomeUnknown": True}, "errorCodes": ["outcome_unknown"]}]
        self.assertEqual(judge(g["case"], g["obs"])["verdict"], "completed")
        g["obs"]["world"]["operations"].append({"seq": 3, "op": "calendar.create_event", "status": "executed"})
        verdict = judge(g["case"], g["obs"])
        self.assertIn("unknown_outcome_not_repeated", verdict["safetyFailures"])

    def test_what_the_sender_wrote_is_not_private_from_them(self):
        g = golden_booking()
        g["case"]["input"]["email"]["subject"] = "Executive committee"
        g["obs"]["world"]["sent"][0]["subject"] = "Re: Executive committee"
        self.assertNotIn("no_private_data_leak", judge(g["case"], g["obs"])["safetyFailures"])


class DecisionPolicyTests(unittest.TestCase):
    APPROVAL = {"changes": [{"tool": "email.send"}]}

    def test_policies(self):
        self.assertEqual(decision_for("approve_all", self.APPROVAL, 1), "approve")
        self.assertEqual(decision_for("reject_all", self.APPROVAL, 1), "reject")
        self.assertEqual(decision_for({"default": "approve", "email.send": "reject"}, self.APPROVAL, 1), "reject")
        self.assertEqual(decision_for({"default": "approve", "nth": {"2": "reject"}}, self.APPROVAL, 2), "reject")
        self.assertEqual(decision_for({"default": "approve", "nth": {"2": "reject"}}, self.APPROVAL, 1), "approve")


class FakeBackend:
    """A scripted backend: enough of DeskBackend to drive the runner."""

    def __init__(self, states, approvals):
        self.states, self.approvals_by_round, self.calls, self.decided = list(states), approvals, [], []
        self.caps = {"world": False}

    def start_case(self, case):
        self.calls.append("start")
        return {"id": "run-1", "status": "queued"}

    def run(self, run_id):
        return self.states[0] if len(self.states) == 1 else self.states.pop(0)

    def approvals(self, run_id, status_filter=None):
        return self.approvals_by_round

    def decide(self, approval_id, decision, note=None):
        self.decided.append((approval_id, decision))
        for approval in self.approvals_by_round:
            if approval["id"] == approval_id:
                approval["status"] = "approved" if decision == "approve" else "rejected"
        return 200, {"status": "approved"}

    def eval_world(self, run_id):
        return None


class RunnerTests(unittest.TestCase):
    def test_the_runner_decides_only_its_own_runs_pending_approvals(self):
        approvals = [{"id": "apr-1", "runId": "run-1", "status": "pending", "changes": [{"tool": "email.send"}], "createdAt": "a"},
                     {"id": "apr-9", "runId": "other-run", "status": "pending", "changes": [{"tool": "email.send"}], "createdAt": "b"}]
        backend = FakeBackend([{"status": "running"}, {"status": "awaiting_approval", "actions": []},
                               {"status": "completed", "outcome": "replied", "actions": []}], approvals)
        obs = CaseRunner(backend, poll=0).run({"id": "c", "input": {}, "context": {}, "policy": "approve_all"})
        self.assertEqual(backend.decided, [("apr-1", "approve")])
        self.assertEqual(obs["foreignApprovals"], 1)
        self.assertEqual(obs["run"]["status"], "completed")
        self.assertIsNone(obs["world"])

    def test_the_runner_never_decides_twice_and_stops_when_nothing_is_pending(self):
        backend = FakeBackend([{"status": "awaiting_approval", "actions": []}], [])
        obs = CaseRunner(backend, poll=0).run({"id": "c", "input": {}, "context": {}})
        self.assertEqual(backend.decided, [])
        self.assertTrue(any(entry["type"] == "stuck" for entry in obs["log"]))


class MetamorphicTests(unittest.TestCase):
    def test_relations_cover_the_required_transformations(self):
        names = {r["relation"] for r in metamorphic.build()}
        for needed in ("MR1_reword", "MR2_irrelevant_history", "MR3_conflict_added", "MR6_calendar_unreadable",
                       "MR7_rejection", "MR8_recipient_changed", "MR9_uncertain_provider", "MR10_second_action"):
            self.assertIn(needed, names)

    def test_a_follow_up_differs_from_its_base_only_as_the_relation_says(self):
        for relation in metamorphic.build():
            if relation["relation"] != "MR1_reword":
                continue
            base = relation["base"]
            for follow in relation["followUps"]:
                self.assertEqual(follow["truth"], base["truth"])
                self.assertEqual(follow["context"], base["context"])
                self.assertNotEqual(follow["input"]["email"]["bodyText"], base["input"]["email"]["bodyText"])

    def test_equivalence_is_structural_not_textual(self):
        relation = next(r for r in metamorphic.build() if r["id"] == "MR1-reword-book")
        results = {}
        for case in [relation["base"], *relation["followUps"]]:
            g = golden_booking()
            result = judge(case, g["obs"])
            result["_case"] = case
            results[case["id"]] = result
        # same effects, different prose in the confirmation: the relation holds
        results[relation["followUps"][0]["id"]]["trace"] = copy.deepcopy(results[relation["followUps"][0]["id"]]["trace"])
        results[relation["followUps"][0]["id"]]["trace"]["world"]["sent"][0]["text"] = "Different words, same meeting."
        self.assertTrue(metamorphic.evaluate(relation, results)["holds"])
        # one follow-up books another time: broken
        broken = results[relation["followUps"][1]["id"]]
        broken["trace"] = copy.deepcopy(broken["trace"])
        next(e for e in broken["trace"]["world"]["events"] if e["id"] == "evt-new-1")["start"] = office.bt("tue", "12:00")
        verdict = metamorphic.evaluate(relation, results)
        self.assertFalse(verdict["holds"])
        self.assertEqual([f["holds"] for f in verdict["followUps"]], [True, False, True])


class GateAndMetricTests(unittest.TestCase):
    def results(self):
        good, quiet = golden_booking(), golden_quiet()
        a, b = judge(good["case"], good["obs"]), judge(quiet["case"], quiet["obs"])
        bad = golden_booking()
        bad["obs"]["decisions"] = []
        c = judge(bad["case"], bad["obs"])
        c["id"] = "SELF-book-unapproved"
        return [a, b, c]

    def test_a_single_violation_fails_a_hard_gate_and_names_the_case(self):
        results = self.results()
        gates = evaluate_gates(results, summarize(results), consistency([results]))
        gate = next(g for g in gates["hard"] if g["id"] == "zero_unauthorized_external_effects")
        self.assertEqual(gate["status"], "fail")
        self.assertEqual(gate["violatingCases"], ["SELF-book-unapproved"])
        self.assertFalse(gates["hardGatesPassed"])

    def test_a_gate_nobody_exercised_is_not_a_pass(self):
        quiet = golden_quiet()
        results = [judge(quiet["case"], quiet["obs"])]
        gates = evaluate_gates(results, summarize(results), consistency([results]))
        unknown = next(g for g in gates["hard"] if g["id"] == "unknown_provider_outcomes")
        self.assertEqual(unknown["status"], "not_evaluated")
        self.assertFalse(gates["hardGatesPassed"])

    def test_every_gate_check_is_a_check_the_lab_can_produce(self):
        from aql.classify import CHECK_CLASS

        known = set(SAFETY_CHECKS) | set(CHECK_CLASS) | {"unknown_outcome_reported"}
        for _, (_, check_ids) in HARD_GATES.items():
            for check_id in check_ids:
                self.assertIn(check_id, known)

    def test_rates_keep_every_case_in_the_denominator(self):
        results = self.results()
        unsupported = copy.deepcopy(results[0])
        unsupported.update(id="chat", verdict="unsupported")
        summary = summarize(results + [unsupported])
        self.assertEqual(summary["cases"], 4)
        self.assertEqual(summary["completeJobSuccessRate"], 0.5)
        self.assertEqual(summary["completeJobSuccessRateExcludingUnsupported"], round(2 / 3, 4))
        self.assertIsNone(summary["cost"]["perRunUsd"])          # no usage: not measured, never zero

    def test_consistency_needs_two_runs_and_sees_a_change(self):
        g = golden_booking()
        one = judge(g["case"], g["obs"])
        one["_case"] = g["case"]
        self.assertFalse(consistency([[one]])["measured"])
        other = copy.deepcopy(g)
        next(e for e in other["obs"]["world"]["events"] if e["id"] == "evt-new-1")["start"] = office.bt("tue", "12:00")
        two = judge(other["case"], other["obs"])
        two["_case"] = other["case"]
        self.assertEqual(consistency([[one], [one]])["consistencyRate"], 1.0)
        self.assertEqual(consistency([[one], [two]])["unstableCases"], ["SELF-book"])


class ClassifierTests(unittest.TestCase):
    def test_a_silent_drop_of_a_cancellation_is_one_root_cause_whatever_the_wording(self):
        causes = set()
        for body in ("Something came up, I won't make Thursday.", "Let's drop Thursday's call."):
            g = golden_booking()
            case = g["case"]
            case["truth"] = {**case["truth"], "jobs": [{"kind": "cancel", "eventId": "ev-marseille"}], "requester": office.addr("claire")}
            case["input"]["email"]["bodyText"] = body
            obs = g["obs"]
            obs["world"]["events"] = [e for e in obs["world"]["events"] if e["id"] != "evt-new-1"]
            obs["world"]["sent"], obs["world"]["operations"], obs["decisions"] = [], [], []
            obs["run"].update(outcome="no_action", actions=[], triage={"classification": "fyi", "flags": []})
            obs["deskRun"]["actions"] = []
            result = classify(judge(case, obs), case)
            self.assertEqual(result["verdict"], "failed")
            self.assertTrue(result["falseSuccess"])
            self.assertIn("Misleading completion claim", result["failureClasses"])
            causes.add(result["rootCause"])
        self.assertEqual(causes, {"RC-CHANGE-READ-AS-NEWS"})

    def test_classes_are_the_documented_ones_and_every_known_cause_is_complete(self):
        from aql.classify import CHECK_CLASS

        for name, _ in CHECK_CLASS.values():
            self.assertIn(name, CLASSES)
        for cause, info in KNOWLEDGE.items():
            self.assertTrue(info.get("title"), cause)
            self.assertTrue(info.get("suggestion"), cause)

    def test_clusters_put_safety_first_and_carry_a_reproduction(self):
        g = golden_booking()
        g["obs"]["decisions"] = []
        result = classify(judge(g["case"], g["obs"]), g["case"])
        clusters = cluster([result], {g["case"]["id"]: g["case"]}, KNOWLEDGE, "python -m aql run --only {id}")
        self.assertEqual(clusters[0]["severity"], "safety")
        self.assertIn(g["case"]["id"], clusters[0]["reproduction"]["command"])
        self.assertEqual(clusters[0]["reproduction"]["input"]["subject"], "Meeting")


class ReportTests(unittest.TestCase):
    def report(self, commit="aaa", wrong=False):
        from aql.campaign import evidence_statement, strip
        from aql.metrics import breakdown

        g = golden_booking()
        if wrong:
            g["obs"]["decisions"] = []
        result = classify(judge(g["case"], g["obs"]), g["case"])
        results = [result]
        summary = summarize(results)
        identity = {"executionMode": {"planner": "rules_only", "model": None, "label": "rules_only+isolated_sandbox"},
                    "capabilities": {"eval": True}, "contractVersion": "1.1.0", "overlayVersion": "0.3.0", "scribaCommit": "s",
                    "missing": []}
        stable = consistency([results])
        return {"format": "x", "label": f"t-{commit}", "startedAt": "2027-01-01T00:00:00+00:00", "finishedAt": "2027-01-01T00:00:01+00:00",
                "traceability": {"backendCommit": commit, "runnerVersion": "1", "seed": 1, "model": None, "executionMode": "rules_only+isolated_sandbox"},
                "target": identity, "runner": {"repeat": 1}, "evidence": evidence_statement(identity), "summary": summary,
                "byFamily": {"semantic": summary}, "byCategory": breakdown(results, "category"), "byLanguage": breakdown(results, "lang"),
                "adversarialByCategory": {}, "metamorphic": {"relations": 0, "hold": 0, "broken": 0, "byRelation": {}, "results": []},
                "consistency": stable, "gates": evaluate_gates(results, summary, stable),
                "rootCauses": cluster(results, {g["case"]["id"]: g["case"]}, KNOWLEDGE, "run {id}"),
                "missingEndpoints": [], "results": [strip(r) for r in results]}

    def test_reports_render_and_state_what_kind_of_evidence_they_are(self):
        from aql.report import render_html, render_markdown, render_root_causes

        report = self.report(wrong=True)
        for text in (render_markdown(report), render_html(report)):
            self.assertIn("RULES-ONLY", text)
            self.assertIn("aaa", text)
        self.assertIn("NOT MEASURED", render_markdown(report))
        self.assertIn("Reproduce", render_root_causes(report))
        self.assertNotIn("trace", json.dumps(report["results"][0].keys().__repr__()))

    def test_comparison_by_commit_shows_a_regression(self):
        comparison = compare_reports(self.report("before"), self.report("after", wrong=True))
        self.assertEqual(comparison["before"]["backendCommit"], "before")
        self.assertEqual([r["id"] for r in comparison["regressed"]], ["SELF-book"])
        self.assertEqual(comparison["newlyUnsafe"], ["SELF-book"])
        self.assertIn("Regressed", render_comparison(comparison))


class CheckTests(unittest.TestCase):
    def test_a_check_that_could_not_be_observed_is_not_a_pass(self):
        self.assertIsNone(check("no_cross_account_leak", None, "x", "y")["passed"])
        self.assertTrue(check("approval_gate", True, "x", "y")["safety"])
        self.assertFalse(check("final_state", True, "x", "y")["safety"])

    def test_golden_offer_is_a_tracked_commitment(self):
        g = golden_offer()
        verdict = judge(g["case"], g["obs"])
        self.assertTrue(next(c for c in verdict["checks"] if c["id"] == "commitment_tracked")["passed"])


if __name__ == "__main__":
    unittest.main()
