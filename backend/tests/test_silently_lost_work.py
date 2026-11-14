"""Three ways work used to be lost without anyone being told (overlay 0.5).

1. A message from a person is not "informational" by default: no work has to
   be ESTABLISHED, or it is handed over.
2. A message that asks for several things is not complete while one of them
   is neither acted on nor seen by the person.
3. A reply that only says the answer is coming does not satisfy a wait.

The wording in these tests was written for them and is used nowhere else: not
in the rules, not in the scenarios, not in the other agents' corpora.
"""
import datetime as dt

import pytest

from desk_overlay import requests

from .test_engine import NOW, SOFIA, Desk, offered
from .test_plans import intent, modelled

PERSON = "Imogen Tavares <imogen@portside.example>"
DAY = dt.timedelta(days=1)


@pytest.fixture()
def desk():
    return Desk()


def deliver(desk, body, subject="Portside", sender=PERSON, message_id="w1", thread=None):
    desk.world().deliver(message_id=message_id, from_addr=sender, subject=subject, body=body,
                         thread_id=thread or f"T-{message_id}")
    return desk.intake(message_id).json()


# ── 1. unknown is not informational ─────────────────────────────────────────

@pytest.mark.parametrize("body", [
    "The harbour authority has suspended our berth licence with effect from Monday.",
    "Two of the crane operators walked off shift this morning over the rota.",
    "Our insurer has declined the storm-damage claim for warehouse four.",
    "I have been approached by a competitor and wanted you to hear it from me first.\n\nThanks,\nImogen",
    "The customs broker says the consignment is being held pending an inspection.\n\nBest,\nImogen",
])
def test_news_from_a_person_that_may_need_judgement_is_handed_over(desk, body):
    run = deliver(desk, body)
    assert run["actions"] == []
    assert run["lifecycle"]["stage"] != "COMPLETED", run["lifecycle"]
    assert run["lifecycle"]["final"] is False


def test_a_sign_off_that_says_thanks_does_not_make_a_message_news(desk):
    run = deliver(desk, "Hi Layla,\n\nThe landlord wants to end the depot lease early.\n\nThanks,\nImogen")
    assert run["held"]["reason"] == "needs_review" and run["lifecycle"]["stage"] == "ESCALATED"


@pytest.mark.parametrize("body", [
    "For your information only: the quay resurfacing finished a day early.",
    "Just a heads-up that the new gate passes arrive on Thursday. No need to reply.",
    "Got it, thank you.",
    "Noted, see you then.",
])
def test_no_work_is_established_only_when_the_message_says_so_or_merely_acknowledges(desk, body):
    run = deliver(desk, body)
    assert run["held"] is None and run["lifecycle"]["stage"] == "COMPLETED"


def test_saying_fyi_does_not_cover_a_request_in_the_same_message(desk):
    run = deliver(desk, "FYI the audit starts Monday. Could you send the auditors the fixed-asset register?")
    assert run["lifecycle"]["stage"] != "COMPLETED" or run["actions"]


def test_the_pure_reading():
    assert requests.no_work_established("Update", "FYI, the quay is open again.")
    assert not requests.no_work_established("Update", "The quay is closed until further notice.")
    assert not requests.no_work_established("Update", "FYI, the quay is closed. Could you ring the port agent?")
    assert not requests.no_work_established("Update", "Is the quay open again?")
    assert requests.no_work_established("Re: Update", "Thanks, received.")


# ── 2. a compound request is not complete while a part of it is open ────────

def test_a_second_thing_asked_beside_a_meeting_is_recorded_with_its_own_date(desk):
    """Rules only. The second request used to vanish, and its date used to
    make the meeting's time unreadable."""
    desk.gateway.model_available = False         # the rules read the time, as with no model configured
    desk.world().deliver(
        message_id="c1", from_addr=SOFIA, subject="Berth plan", thread_id="T-c1",
        body="Could we meet Tuesday at 10:00 for 30 minutes to agree the berth plan? "
             "Please also forward the tide tables to the pilots by Monday noon.")
    run = desk.intake("c1").json()
    by_tool = {a["tool_name"]: a for a in run["actions"]}
    assert set(by_tool) == {"create_calendar_event", "create_task"}
    assert by_tool["create_calendar_event"]["input"]["start"].startswith("2026-11-17T10:00")
    assert by_tool["create_task"]["input"]["title"] == "Forward the tide tables to the pilots by Monday noon"
    assert by_tool["create_task"]["input"]["due_at"].startswith("2026-11-16T12:00")


def test_two_things_to_do_are_two_tasks_each_with_its_own_date(desk):
    run = deliver(desk, "I need your signature on the towage agreement by Wednesday. "
                        "Please also renew the pilotage licence before Friday noon.", subject="Two things")
    assert run["category"] == "action_item"
    tasks = sorted((a["input"]["title"], a["input"].get("due_at", "")[:13]) for a in run["actions"]
                   if a["tool_name"] == "create_task")
    assert tasks == [("I need your signature on the towage agreement by Wednesday", "2026-11-18T17"),
                     ("Renew the pilotage licence before Friday noon", "2026-11-20T12")]


def test_asking_to_be_answered_is_not_a_second_piece_of_work(desk):
    desk.gateway.model_available = False
    desk.world().deliver(message_id="c2", from_addr=SOFIA, subject="Berth plan", thread_id="T-c2",
                         body="Could we meet Tuesday at 10:00 for 30 minutes? Please let me know if that suits you.")
    run = desk.intake("c2").json()
    assert [a["tool_name"] for a in run["actions"]] == ["create_calendar_event"]
    assert run["unresolved"] == []


def test_a_request_that_was_read_and_not_acted_on_keeps_the_run_open(desk):
    """With a model's reading: a meeting is booked, and a reminder it also
    read has no time. Booking the meeting does not complete the run."""
    modelled(desk, {"intents": [
        intent("new_meeting", "Could we meet Tuesday at 10:00", requested_start="2026-11-17T10:00:00+00:00",
               requested_end="2026-11-17T10:30:00+00:00"),
        intent("reminder", "remind yourself to bring the survey", title="Bring the survey")]})
    desk.world().deliver(message_id="c3", from_addr=SOFIA, subject="Survey", thread_id="T-c3",
                         body="Could we meet Tuesday at 10:00? And remind yourself to bring the survey.")
    run = desk.intake("c3").json()
    assert [u["why"] for u in run["unresolved"]] == ["details_missing"] and run["unresolved"][0]["resolved"] is False
    done = run
    for _ in range(4):                       # approve everything the Desk proposes, as it comes
        for action in done["actions"]:
            if action["status"] == "awaiting_approval":
                desk.gateway.settle(action["toolCallId"], "executed")
        done = desk.post(f"/runs/{run['runId']}/advance").json()
    assert all(a["status"] == "executed" for a in done["actions"])
    assert "create_calendar_event" in [a["tool_name"] for a in done["actions"]]
    assert done["lifecycle"]["stage"] == "ESCALATED" and done["lifecycle"]["reason"] == "unresolved_requests"
    assert done["lifecycle"]["final"] is False and "resolve_unresolved" in done["next"]

    taken = desk.post(f"/runs/{run['runId']}/unresolved/resolve").json()
    assert taken["unresolved"][0]["resolved"] is True and "resolve_unresolved" not in taken["next"]
    assert taken["lifecycle"]["stage"] == "COMPLETED"
    assert desk.post(f"/runs/{run['runId']}/unresolved/resolve").json()["lifecycle"]["stage"] == "COMPLETED"


def test_a_reply_that_is_needed_beside_recorded_work_keeps_the_run_open(desk):
    modelled(desk, {"intents": [intent("task", "send the manifest by Friday", title="Send the manifest"),
                                intent("reply_needed", "which berth do you prefer")]})
    desk.world().auto_internal_writes = True
    run = deliver(desk, "Please send the manifest by Friday. Also, which berth do you prefer for the Altair?")
    assert [a["status"] for a in run["actions"]] == ["executed"]
    assert [u["why"] for u in run["unresolved"]] == ["reply_needs_author"]
    assert run["lifecycle"]["stage"] == "ESCALATED" and run["lifecycle"]["reason"] == "unresolved_requests"


def test_sentences_that_ask_are_found_by_their_form():
    found = requests.units("x", "Hi Layla,\n\nThe tug is booked. Please also ring the harbour master before noon. "
                                "Would you mind signing the pilot's log? Let me know.\n\nThanks,\nImogen")
    assert [(u["kind"], u["text"][:20]) for u in found] == [
        ("action", "Please also ring the"), ("action", "Would you mind signi")]
    assert [u["kind"] for u in requests.units("x", "Could you let me know whether that suits?")] == ["answer"]
    assert [u["kind"] for u in requests.units("x", "Is the gate open on Sunday for us?")] == ["answer"]
    title = requests.title_of("Also, could you please ring the harbour master before noon?")
    assert title == "Ring the harbour master before noon"


# ── 3. a holding reply is not the answer ────────────────────────────────────

@pytest.mark.parametrize("holding", [
    "Bear with me, finance have not signed it off yet.",
    "I'm chasing the surveyor and should have it for you Thursday.",
    "Not there yet I'm afraid, we need another day or two.",
    "Out of office until Monday, I will pick this up then.",
])
def test_a_reply_that_puts_the_answer_off_leaves_the_wait_open(desk, holding):
    run = offered(desk)
    desk.world().set_now(NOW + dt.timedelta(hours=3))
    desk.world().deliver(message_id="h1", from_addr=SOFIA, subject="Re: Intro call next week?", body=holding,
                         thread_id="T-m1")
    listed = desk.get("/follow-ups").json()
    assert listed["counts"]["waiting"] == 1 and listed["counts"]["satisfied"] == 0
    follow = listed["followUps"][0]
    assert follow["reason"] == "holding_reply" and follow["lastHoldingReplyId"] == "h1"
    assert desk.get(f"/runs/{run['runId']}").json()["lifecycle"]["stage"] == "WAITING_FOR_RESPONSE"

    # The real answer still satisfies it.
    desk.world().set_now(NOW + dt.timedelta(hours=6))
    desk.world().deliver(message_id="h2", from_addr=SOFIA, subject="Re: Intro call next week?",
                         body="Wednesday at 10:00 works for us.", thread_id="T-m1")
    after = desk.get("/follow-ups").json()
    assert after["counts"]["satisfied"] == 1 and after["followUps"][0]["satisfiedBy"] == "h2"


def test_a_holding_reply_still_lets_the_wait_become_overdue(desk):
    offered(desk)
    desk.world().set_now(NOW + dt.timedelta(hours=3))
    desk.world().deliver(message_id="h1", from_addr=SOFIA, subject="Re: Intro call next week?",
                         body="Still waiting on our side, will revert.", thread_id="T-m1")
    desk.get("/follow-ups")
    desk.world().set_now(NOW + 3 * DAY)
    assert desk.get("/follow-ups").json()["counts"]["overdue"] == 1


def test_a_holding_reply_to_a_wait_the_desk_did_not_open_keeps_it_open_and_is_filed(desk):
    desk.world().follow_ups.append({
        "id": "fu-cert", "subject": "Classification certificate", "threadId": "T-cert", "status": "waiting",
        "waitingOn": {"name": "Imogen", "email": "imogen@portside.example"},
        "sentAt": "2026-11-12T10:00:00+00:00", "expectedBy": "2026-11-20T17:00:00+00:00"})
    run = deliver(desk, "The surveyor is still going through it, I will send it as soon as I have it.",
                  subject="Re: Classification certificate", thread="T-cert")
    assert desk.world().follow_ups[0]["status"] == "waiting"
    assert run["followUps"][0]["reason"] == "holding_reply" and run["followUps"][0]["state"] == "waiting"
    assert run["held"] is None and run["lifecycle"]["stage"] in ("COMPLETED", "WAITING_FOR_RESPONSE")

    answered = deliver(desk, "The certificate is attached, signed by the surveyor.", message_id="w2",
                       subject="Re: Classification certificate", thread="T-cert")
    assert desk.world().follow_ups[0]["status"] == "closed" and answered["followUps"][0]["state"] == "satisfied"


def test_what_counts_as_putting_an_answer_off():
    assert requests.is_holding_reply("Bear with me, I'll have it by Thursday.")
    assert requests.is_holding_reply("We are still waiting for the bank.")
    assert not requests.is_holding_reply("Please find the signed copy attached.")
    assert not requests.is_holding_reply("Yes, Thursday at 10 works.")
    assert not requests.is_holding_reply("I will send the rest later, but the main schedule is attached.")


# ── what a request is not ───────────────────────────────────────────────────

FOOTER = ("Could we meet Tuesday at 10:00 for 30 minutes?\n\nKind regards,\nImogen Tavares\nPortside Agency\n"
          "Please consider the environment before printing this email. If you are not the intended recipient "
          "please notify the sender and delete it.")


def test_a_footer_or_a_disclaimer_is_never_a_request(desk):
    desk.gateway.model_available = False
    desk.world().deliver(message_id="f1", from_addr=SOFIA, subject="Berth plan", thread_id="T-f1", body=FOOTER)
    run = desk.intake("f1").json()
    assert [a["tool_name"] for a in run["actions"]] == ["create_calendar_event"] and run["unresolved"] == []
    assert requests.units("x", FOOTER) == [{"text": "Could we meet Tuesday at 10:00 for 30 minutes?",
                                            "kind": "scheduling", "intent": "new"}]


def test_a_request_that_names_an_address_is_handed_over_never_recorded_or_obeyed(desk):
    desk.gateway.model_available = False
    desk.world().deliver(
        message_id="a1", from_addr=SOFIA, subject="Berth plan", thread_id="T-a1",
        body="Could we meet Tuesday at 10:00 for 30 minutes? Please also loop in harbour@thirdparty.example.")
    run = desk.intake("a1").json()
    assert [a["tool_name"] for a in run["actions"]] == ["create_calendar_event"]
    assert run["actions"][0]["input"]["attendees"] == ["sofia@client.example"]
    assert [u["why"] for u in run["unresolved"]] == ["names_an_address"]
    assert "thirdparty" not in str(run["actions"])


def test_an_ask_that_is_not_clearly_separate_work_is_shown_not_turned_into_a_task(desk):
    desk.gateway.model_available = False
    desk.world().deliver(message_id="s1", from_addr=SOFIA, subject="Berth plan", thread_id="T-s1",
                         body="Could we meet Tuesday at 10:00 for 30 minutes? Please bring the tide tables.")
    run = desk.intake("s1").json()
    assert [a["tool_name"] for a in run["actions"]] == ["create_calendar_event"]
    assert [u["why"] for u in run["unresolved"]] == ["needs_your_decision"]


def test_two_deadlines_in_one_sentence_are_two_tasks(desk):
    run = deliver(desk, "I need two things from you: review the dredging quote by Wednesday, "
                        "and countersign the pilotage agreement by Friday.", subject="Two things")
    tasks = sorted((a["input"]["title"], a["input"].get("due_at", "")[:10]) for a in run["actions"]
                   if a["tool_name"] == "create_task")
    assert tasks == [("Countersign the pilotage agreement by Friday", "2026-11-20"),
                     ("Review the dredging quote by Wednesday", "2026-11-18")]


def test_cancel_this_one_and_could_we_meet_then_is_not_done_when_only_the_first_is(desk):
    desk.gateway.model_available = False
    desk.world().add_event(provider="google", event_id="evt-tow", title="Towage review",
                           start="2026-11-17T09:00:00+00:00", end="2026-11-17T10:00:00+00:00",
                           attendees=["sofia@client.example"])
    desk.world().deliver(
        message_id="x1", from_addr=SOFIA, subject="Towage review", thread_id="T-x1",
        body="I cannot make the towage review tomorrow, please cancel it. Could we meet on Thursday at 14:00 instead?")
    run = desk.intake("x1").json()
    assert [u["why"] for u in run["unresolved"]] == ["second_scheduling_request"]
    for action in run["actions"]:
        if action["status"] == "awaiting_approval":
            desk.gateway.settle(action["toolCallId"], "executed")
    done = desk.post(f"/runs/{run['runId']}/advance").json()
    assert done["lifecycle"]["stage"] != "COMPLETED"


def test_a_question_that_begins_remind_me_is_not_a_reminder_to_set(desk):
    from desk_overlay import reading

    assert not reading.reminder_request("Remind me, which quay did we settle on for the Altair?")
    assert reading.reminder_request("Remind me on Wednesday at 09:00 to ring the chairman.")
    assert reading.reminder_request("Please remind yourself to bring the survey.")
