"""Follow-ups as records with a life: waiting, overdue, reminded once,
escalated, satisfied, closed. Nothing is chased twice and nothing is
duplicated; all of it is derived from what is stored on the runs.
"""
import datetime as dt

import pytest

from .test_engine import EXEC, NOW, SOFIA, Desk, offered

DAY = dt.timedelta(days=1)


@pytest.fixture()
def desk():
    return Desk()


def listed(desk):
    return desk.get("/follow-ups").json()


def test_overdue_then_one_reminder_then_it_is_the_persons_and_never_a_second_reminder(desk):
    run = offered(desk)
    desk.world().set_now(NOW + 3 * DAY)
    first = listed(desk)
    assert first["counts"]["overdue"] == 1 and first["followUps"][0]["nudgePending"] is True
    view = desk.get(f"/runs/{run['runId']}").json()
    nudge = next(a for a in view["actions"] if a["purpose"] == "nudge")
    assert nudge["followUpId"] == run["followUps"][0]["id"] and nudge["status"] == "awaiting_approval"

    # The reminder is approved and sent. It is one reminder for the same wait, not a new wait.
    desk.gateway.settle(nudge["toolCallId"], "executed")
    desk.post(f"/runs/{run['runId']}/advance")
    after = listed(desk)
    assert len(after["followUps"]) == 1 and after["followUps"][0]["nudges"] == 1
    assert after["followUps"][0]["nudgePending"] is False

    # Still silent two days after the reminder: escalated, and nothing more is proposed.
    desk.world().set_now(NOW + 6 * DAY)
    late = listed(desk)
    assert late["counts"]["escalated"] == 1 and late["followUps"][0]["reason"] == "no_answer_after_reminder"
    listed(desk)
    final = desk.get(f"/runs/{run['runId']}").json()
    assert len([a for a in final["actions"] if a["purpose"] == "nudge"]) == 1
    assert final["lifecycle"]["stage"] == "WAITING_FOR_RESPONSE"
    assert [s["to"] for s in desk.world().sent] == []           # the Desk itself sent nothing


def test_an_answer_after_the_reminder_still_satisfies_it(desk):
    run = offered(desk)
    desk.world().set_now(NOW + 3 * DAY)
    listed(desk)
    desk.world().deliver(message_id="m9", from_addr=SOFIA, subject="Re: Intro call next week?",
                         body="Sorry for the delay: Wednesday at 10 works.", thread_id="T-m1")
    after = listed(desk)
    assert after["counts"]["satisfied"] == 1 and after["counts"]["overdue"] == 0
    assert desk.get(f"/runs/{run['runId']}").json()["followUps"][0]["satisfiedBy"] == "m9"


def test_an_escalated_follow_up_can_be_closed_by_the_person(desk):
    run = offered(desk)
    desk.world().set_now(NOW + 3 * DAY)
    listed(desk)
    view = desk.get(f"/runs/{run['runId']}").json()
    desk.gateway.settle(next(a for a in view["actions"] if a["purpose"] == "nudge")["toolCallId"], "executed")
    desk.world().set_now(NOW + 7 * DAY)
    assert listed(desk)["counts"]["escalated"] == 1
    closed = desk.post(f"/runs/{run['runId']}/follow-ups/{run['followUps'][0]['id']}/close").json()
    assert closed["followUps"][0]["state"] == "closed" and closed["lifecycle"]["stage"] == "COMPLETED"


def test_waits_that_predate_the_desk_are_listed_and_become_overdue(desk):
    desk.world().follow_ups.extend([
        {"id": "fu-a", "subject": "Terms", "threadId": "T-a", "status": "waiting",
         "waitingOn": {"name": "Peter", "email": "Peter@Altamira.example"},
         "sentAt": "2026-11-11T10:00:00+00:00", "expectedBy": "2026-11-13T17:00:00+00:00"},
        {"id": "fu-b", "subject": "Forecast", "threadId": "T-b", "status": "waiting",
         "waitingOn": {"name": "Hannah", "email": "hannah@nordhavn.example"},
         "sentAt": "2026-11-13T10:00:00+00:00", "expectedBy": "2026-11-17T17:00:00+00:00"},
        {"id": "fu-c", "subject": "Old", "threadId": "T-c", "status": "closed",
         "waitingOn": {"name": "X", "email": "x@x.example"}, "expectedBy": "2026-11-01T17:00:00+00:00"}])
    found = {f["id"]: f for f in listed(desk)["followUps"]}
    assert set(found) == {"fu-a", "fu-b"}
    assert found["fu-a"]["state"] == "overdue" and found["fu-a"]["waitingOn"] == "peter@altamira.example"
    assert found["fu-a"]["source"] == "external" and found["fu-a"]["runId"] is None
    assert found["fu-b"]["state"] == "waiting" and found["fu-b"]["nudges"] == 0


def test_the_executives_own_overdue_tasks_are_listed_beside_the_waits(desk):
    desk.world().tasks.extend([
        {"id": "t1", "title": "Sign the lease", "status": "open", "due_at": "2026-11-14T17:00:00+00:00"},
        {"id": "t2", "title": "Board pack", "status": "open", "due_at": "2026-11-20T17:00:00+00:00"},
        {"id": "t3", "title": "Paid invoice", "status": "done", "due_at": "2026-11-10T17:00:00+00:00"},
        {"id": "t4", "title": "No date", "status": "open"}])
    assert [t["id"] for t in listed(desk)["overdueTasks"]] == ["t1"]


def test_two_replies_to_the_same_person_in_one_conversation_are_one_wait(desk):
    run = offered(desk)
    # A second reply that would also await an answer, in the same thread to the same person.
    workflow, user = desk.workflow, desk.gateway.users[EXEC]["user"]
    stored = desk.gateway.get_run(user, run["runId"])
    card = workflow._propose(user, stored, {
        "tool_name": "send_email", "purpose": "clarify", "reason": "x",
        "tool_input": {"provider": "gmail", "mode": "reply", "to": "sofia@client.example",
                       "subject": "Re: Intro", "body": "Which day suits you?", "thread_id": "T-m1",
                       "email_id": "m1"}})
    desk.gateway.settle(card["id"], "executed")
    after = desk.post(f"/runs/{run['runId']}/advance").json()
    assert len(after["followUps"]) == 1
