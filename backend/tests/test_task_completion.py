"""A message that reports finished work closes the open task it is about.

Deterministic: which task is meant is decided by the message's own words, and
only when exactly one open task matches. A model may say "this reports
finished work"; it never chooses the task.
"""
import pytest

from desk_overlay import planning

from .test_engine import EXEC, OTHER, Desk
from .test_plans import intent, modelled

YARA = "Yara Nassar <yara@holdings.example>"
DONE = "The NDA with Lumen Events is countersigned and filed in the contracts folder. No action needed."


@pytest.fixture()
def desk():
    desk = Desk()
    desk.world().tasks.extend([
        {"id": "t-nda", "title": "Get the NDA with Lumen Events countersigned", "status": "open"},
        {"id": "t-board", "title": "Sign off the Q3 board pack", "status": "open"}])
    return desk


def report(desk, body=DONE, subject="NDA with Lumen Events: countersigned copy", message_id="n1", user=EXEC):
    desk.world(user).deliver(message_id=message_id, from_addr=YARA, subject=subject, body=body,
                             thread_id=f"T-{message_id}")
    return desk.intake(message_id, user=user).json()


def status(desk, task_id):
    return next(t["status"] for t in desk.world().tasks if t["id"] == task_id)


def test_finished_work_is_suggested_and_nothing_is_changed_until_the_person_says_so(desk):
    run = report(desk)
    assert run["actions"] == []                                   # no new task, no mail, no calendar
    [update] = run["taskUpdates"]
    assert update["taskId"] == "t-nda" and update["state"] == "suggested" and update["source"] == "rules"
    assert run["next"] == ["complete_task"]
    assert run["lifecycle"]["stage"] == "ESCALATED" and run["lifecycle"]["reason"] == "task_completion_suggested"
    assert status(desk, "t-nda") == "open"

    done = desk.post(f"/runs/{run['runId']}/task-updates/t-nda/apply").json()
    assert done["taskUpdates"][0]["state"] == "completed" and done["taskUpdates"][0]["verified"] is True
    assert done["taskUpdates"][0]["by"] == EXEC
    assert done["lifecycle"]["stage"] == "COMPLETED" and done["lifecycle"]["reason"] == "task_completed"
    assert status(desk, "t-nda") == "done" and status(desk, "t-board") == "open"
    assert done["next"] == []


def test_where_the_policy_allows_own_records_it_is_done_at_once_and_verified(desk):
    desk.world().auto_internal_writes = True
    run = report(desk)
    assert run["taskUpdates"][0]["state"] == "completed" and run["taskUpdates"][0]["by"] == "policy"
    assert run["taskUpdates"][0]["verified"] is True
    assert status(desk, "t-nda") == "done" and status(desk, "t-board") == "open"
    assert [e["op"] for e in desk.world().oplog] == ["task.complete"]
    assert run["lifecycle"]["stage"] == "COMPLETED"


def test_applying_twice_marks_it_done_once(desk):
    run = report(desk)
    for _ in range(3):
        again = desk.post(f"/runs/{run['runId']}/task-updates/t-nda/apply").json()
    assert again["taskUpdates"][0]["state"] == "completed"
    assert [e["op"] for e in desk.world().oplog] == ["task.complete"]


def test_a_dismissed_suggestion_changes_nothing(desk):
    run = report(desk)
    after = desk.post(f"/runs/{run['runId']}/task-updates/t-nda/dismiss").json()
    assert after["taskUpdates"][0]["state"] == "dismissed" and after["next"] == []
    assert status(desk, "t-nda") == "open" and desk.world().oplog == []
    assert after["lifecycle"]["stage"] == "COMPLETED"


def test_two_tasks_it_could_mean_and_none_is_marked(desk):
    desk.world().auto_internal_writes = True
    desk.world().tasks.append({"id": "t-nda2", "title": "Get the NDA with Lumen Events filed", "status": "open"})
    run = report(desk)
    assert run["taskUpdates"] == [] and status(desk, "t-nda") == "open" and status(desk, "t-nda2") == "open"
    assert "task_match_ambiguous" in [i["data"].get("reason") for i in run["timeline"] if i["kind"] == "decision"]


@pytest.mark.parametrize("body", [
    "The NDA with Lumen Events is still not countersigned.",
    "Is the NDA with Lumen Events countersigned yet?",
    "The NDA with Lumen Events is countersigned. Please file it in the contracts folder.",
    "The NDA with Lumen Events will be countersigned tomorrow.",
])
def test_a_message_that_is_not_a_report_of_finished_work_closes_nothing(desk, body):
    desk.world().auto_internal_writes = True
    run = report(desk, body=body)
    assert run["taskUpdates"] == [] and status(desk, "t-nda") == "open"


def test_finished_work_that_matches_no_task_is_just_news(desk):
    desk.world().auto_internal_writes = True
    run = report(desk, body="The lease for the Tripoli depot is signed and filed. No action needed.",
                 subject="Tripoli lease")
    assert run["taskUpdates"] == [] and run["actions"] == []
    assert status(desk, "t-nda") == "open" and status(desk, "t-board") == "open"


def test_a_model_may_say_work_is_finished_but_the_words_still_choose_the_task(desk):
    desk.world().auto_internal_writes = True
    # Worded so the rules do not see it; the model reports it and points, wrongly, at another task.
    modelled(desk, {"intents": [{**intent("work_done", "Lumen have put their signature on the NDA"),
                                 "details": {"task_hint": "the NDA"}}]})
    run = report(desk, body="Lumen have put their signature on the NDA, countersigned copy attached, "
                            "with Lumen Events' stamp.")
    [update] = run["taskUpdates"]
    assert update["taskId"] == "t-nda" and update["source"] == "model" and update["state"] == "completed"

    desk2 = Desk()
    desk2.world().tasks.append({"id": "t-board", "title": "Sign off the Q3 board pack", "status": "open"})
    desk2.world().auto_internal_writes = True
    modelled(desk2, {"intents": [{**intent("work_done", "Lumen have put their signature on the NDA"),
                                  "details": {"task_hint": "Sign off the Q3 board pack"}}]})
    desk2.world().deliver(message_id="n1", from_addr=YARA, subject="NDA", thread_id="T-n1",
                          body="Lumen have put their signature on the NDA.")
    run2 = desk2.intake("n1").json()
    # The model's hint names a task the message never mentions: nothing is closed on a hint.
    assert run2["taskUpdates"] == []
    assert desk2.world().tasks[0]["status"] == "open"


def test_another_user_cannot_apply_someone_elses_suggestion(desk):
    run = report(desk)
    assert desk.post(f"/runs/{run['runId']}/task-updates/t-nda/apply", user=OTHER).status_code == 404
    assert status(desk, "t-nda") == "open"
    assert desk.post(f"/runs/{run['runId']}/task-updates/t-other/apply").status_code == 404


def test_a_task_that_vanished_is_reported_as_failed_not_as_done(desk):
    run = report(desk)
    desk.world().tasks[:] = [t for t in desk.world().tasks if t["id"] != "t-nda"]
    after = desk.post(f"/runs/{run['runId']}/task-updates/t-nda/apply").json()
    assert after["taskUpdates"][0]["state"] == "failed"
    assert after["lifecycle"]["stage"] == "ESCALATED" and after["lifecycle"]["reason"] == "task_completion_failed"


def test_matching_needs_most_of_the_title_and_refuses_a_tie():
    tasks = [{"id": 1, "title": "Renew the fleet insurance policy"},
             {"id": 2, "title": "Review the Altamira contract"}]
    assert planning.match_open_task("The fleet insurance policy is renewed.", tasks)["task"]["id"] == 1
    assert planning.match_open_task("The insurance question came up again.", tasks)["status"] == "none"
    twins = [{"id": 1, "title": "Sign the Altamira contract"}, {"id": 2, "title": "Review the Altamira contract"}]
    assert planning.match_open_task("The Altamira contract is signed and reviewed.", twins)["status"] == "several"
    assert planning.work_reported_done("All signed and filed. No action needed.") is True
    assert planning.work_reported_done("Signed? Not yet.") is False


def test_a_completion_that_cannot_be_read_back_is_not_called_done(desk, monkeypatch):
    """The call to mark the task done returned; the tasks cannot be read to
    see it. That is not "completed": the provider accepting a request is not
    the result."""
    run = report(desk)
    gateway = desk.workflow.gateway

    def unreadable(*args, **kwargs):
        raise RuntimeError("tasks unavailable")

    monkeypatch.setattr(gateway, "open_tasks", unreadable)
    after = desk.post(f"/runs/{run['runId']}/task-updates/t-nda/apply").json()
    [update] = after["taskUpdates"]
    assert update["state"] == "unverified" and update.get("verified") is None      # never true without a read-back
    assert update["error"] == "task_not_read_back"
    assert after["lifecycle"]["stage"] == "VERIFYING" and after["lifecycle"]["reason"] == "task_not_verified"
    assert after["lifecycle"]["final"] is False
