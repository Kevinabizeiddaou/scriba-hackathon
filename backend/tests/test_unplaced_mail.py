""""No action" has to be earned.

A message written by a person that the rules cannot place used to end
COMPLETED with nothing proposed: invisible, and wrong whenever it was a
notice of claim, a resignation or a request worded as a statement. It is now
handed over. Mail that says it is for information, automated mail, and news
the Desk acted on stay filed.
"""
import pytest

from .test_engine import Desk
from .test_plans import intent, modelled

PERSON = "Dana Whitfield <dana@partner.example>"


@pytest.fixture()
def desk():
    return Desk()


def deliver(desk, body, subject="A note", sender=PERSON, message_id="u1"):
    desk.world().deliver(message_id=message_id, from_addr=sender, subject=subject, body=body,
                         thread_id=f"T-{message_id}")
    return desk.intake(message_id).json()


@pytest.mark.parametrize("body", [
    "I am writing to give notice that Altamira intends to bring a claim under clause 14.",
    "After a lot of thought I have decided to leave the company at the end of the month.",
    "The auditors are still waiting for the signed representation letter.",
    "Our lender has written about the covenant test for the third quarter.",
])
def test_mail_from_a_person_that_cannot_be_placed_is_handed_over_not_filed(desk, body):
    run = deliver(desk, body)
    if run["category"] != "informational":
        pytest.skip("the rules placed this one")
    assert run["actions"] == [] and run["held"]["reason"] == "needs_review"
    assert run["lifecycle"]["stage"] == "ESCALATED" and run["lifecycle"]["final"] is False


@pytest.mark.parametrize("body", [
    "FYI: the Tripoli depot passed its fire inspection this morning.",
    "Just to let you know, the new forklifts were delivered today.",
    "The lease is signed and filed. No action needed.",
    "Thank you, received with thanks.",
])
def test_mail_that_says_it_is_for_information_stays_filed(desk, body):
    run = deliver(desk, body)
    assert run["actions"] == [] and run["held"] is None
    assert run["lifecycle"]["stage"] == "COMPLETED"


def test_automated_mail_stays_filed(desk):
    run = deliver(desk, "Our weekly digest of logistics news. Unsubscribe here.", subject="Weekly digest",
                  sender="Logistics Weekly <no-reply@news.example>")
    assert run["category"] == "automated" and run["held"] is None
    assert run["lifecycle"]["stage"] == "COMPLETED"


def test_a_model_that_read_it_as_news_has_earned_it(desk):
    modelled(desk, {"intents": [intent("fyi", "Our lender has written about the covenant test")]})
    run = deliver(desk, "Our lender has written about the covenant test for the third quarter.")
    assert run["held"] is None and run["lifecycle"]["stage"] == "COMPLETED"


def test_news_the_desk_acted_on_is_not_handed_over(desk):
    desk.world().tasks.append({"id": "t1", "title": "Renew the fleet insurance policy", "status": "open"})
    desk.world().auto_internal_writes = True
    run = deliver(desk, "The fleet insurance policy is renewed and the certificate is filed.")
    assert run["taskUpdates"][0]["state"] == "completed" and run["held"] is None
    assert run["lifecycle"]["stage"] == "COMPLETED"


def test_a_reply_the_model_says_is_needed_and_nobody_drafted_is_handed_over(desk):
    """Found with a real model: a notice of claim was read as needing a
    reply, nothing was drafted, and the run ended as done with nothing shown."""
    modelled(desk, {"intents": [intent("reply_needed", "intends to bring a claim under clause 14")]})
    run = deliver(desk, "I am writing to give notice that Altamira intends to bring a claim under clause 14.")
    assert run["actions"] == [] and run["held"]["reason"] == "reply_needs_author"
    assert run["lifecycle"]["stage"] == "ESCALATED" and run["lifecycle"]["final"] is False


def test_a_reply_that_was_drafted_is_not_also_a_hand_over(desk):
    modelled(desk, {"intents": [intent("reply_needed", "Could you confirm"),
                                intent("task", "Could you confirm by Friday", title="Confirm the terms")]})
    run = deliver(desk, "Could you confirm by Friday that the terms are acceptable?")
    assert [a["tool_name"] for a in run["actions"]] == ["create_task"] and run["held"] is None
