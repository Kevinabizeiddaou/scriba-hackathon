"""The Desk's own checks on a proposed action. Pure, no Scriba."""
from desk_overlay.safeguards import (
    addresses_in,
    is_gmail_reply,
    recipients_of,
    reply_target_issue,
    structural_issue,
    unverified_recipients,
)


def test_addresses_are_found_in_strings_and_lists_and_lowercased():
    assert addresses_in("Sofia <Sofia@Client.Example>; b@x.example") == ["sofia@client.example", "b@x.example"]
    assert addresses_in(["a@x.example", "A@x.example", "not an address"]) == ["a@x.example"]
    assert addresses_in(None) == []


def test_recipient_fields_per_tool():
    assert recipients_of("send_email", {"to": "a@x.example", "cc": ["b@x.example"]}) == [
        "a@x.example", "b@x.example"]
    assert recipients_of("create_calendar_event", {"attendees": ["a@x.example"]}) == ["a@x.example"]
    assert recipients_of("update_calendar_event", {"add_attendees": ["c@x.example"]}) == ["c@x.example"]
    assert recipients_of("create_task", {"title": "mail a@x.example"}) == []


# ── structure ──────────────────────────────────────────────────────────────

def test_an_email_needs_a_valid_recipient_and_a_body():
    assert structural_issue("send_email", {"to": "", "body": "hi"})[0] == "recipient_required"
    assert structural_issue("send_email", {"to": "Sofia", "body": "hi"})[0] == "recipient_required"
    assert structural_issue("send_email", {"to": "a@x.example, Sofia", "body": "hi"})[0] == "recipient_required"
    assert structural_issue("send_email", {"to": "a@x.example", "body": " "})[0] == "body_required"
    assert structural_issue("send_email", {"to": ["a@x.example"], "text": "hi"}) is None


def test_tasks_reminders_and_events_need_their_essentials():
    assert structural_issue("create_task", {"title": ""})[0] == "title_required"
    assert structural_issue("create_task", {"title": "Send deck"}) is None
    assert structural_issue("create_reminder", {"title": "Call"})[0] == "reminder_incomplete"
    assert structural_issue("create_calendar_event", {"title": "Call"})[0] == "start_required"
    assert structural_issue("create_calendar_event", {"start": "2027-03-04T10:00:00Z"}) is None


# ── who vouched for a recipient ────────────────────────────────────────────

def test_an_address_from_content_is_unverified():
    assert unverified_recipients("send_email", {"to": "billing@attacker.example"},
                                 user_message="Send it to our billing contact", vouched=[]) == [
        "billing@attacker.example"]


def test_the_users_own_words_the_desk_and_the_users_confirmation_each_vouch():
    card = {"to": "a@x.example, b@x.example, c@x.example, me@own.example",
            "desk_verified_recipients": ["b@x.example"], "desk_confirmed_recipients": ["c@x.example"]}
    assert unverified_recipients("send_email", card, user_message="write to A@X.example please",
                                 vouched=["me@own.example"]) == []


def test_at_approval_there_is_no_user_message_so_only_recorded_verification_counts():
    card = {"attendees": ["a@x.example", "new@x.example"], "desk_verified_recipients": ["a@x.example"]}
    assert unverified_recipients("create_calendar_event", card, user_message=None, vouched=[]) == [
        "new@x.example"]


# ── is the message being answered still the latest in its thread ───────────

def row(item_id, minute, thread="T1"):
    return {"id": item_id, "threadId": thread, "timestamp": f"2027-03-01T07:{minute:02d}:00+00:00"}


REPLY = {"provider": "gmail", "mode": "reply", "thread_id": "T1", "email_id": "m1"}


def test_only_gmail_replies_in_a_thread_are_checked():
    assert is_gmail_reply("send_email", REPLY) is True
    assert is_gmail_reply("send_email", {**REPLY, "provider": "outlook"}) is False
    assert is_gmail_reply("send_email", {**REPLY, "mode": "compose"}) is False
    assert is_gmail_reply("send_email", {**REPLY, "thread_id": ""}) is False
    assert is_gmail_reply("create_task", REPLY) is False


def test_the_latest_message_in_the_thread_can_be_answered():
    assert reply_target_issue(REPLY, inbox_rows=[row("m1", 10), row("other", 50, "T2")], sent_rows=[]) is None


def test_a_newer_inbound_message_in_the_thread_holds_the_reply():
    assert reply_target_issue(REPLY, inbox_rows=[row("m1", 10), row("m2", 20)], sent_rows=[])[0] == \
        "reply_target_changed"


def test_the_users_own_later_message_in_the_thread_holds_the_reply():
    sent = [{"id": "s1", "thread_id": "T1", "sent_at": "2027-03-01T07:30:00+00:00"}]
    assert reply_target_issue(REPLY, inbox_rows=[row("m1", 10)], sent_rows=sent)[0] == "reply_target_changed"


def test_an_earlier_sent_message_or_one_in_another_thread_does_not():
    sent = [{"id": "s0", "thread_id": "T1", "sent_at": "2027-03-01T07:05:00+00:00"},
            {"id": "s9", "thread_id": "T9", "sent_at": "2027-03-01T08:00:00+00:00"}]
    assert reply_target_issue(REPLY, inbox_rows=[row("m1", 10)], sent_rows=sent) is None


def test_unknown_is_not_treated_as_nothing_newer():
    assert reply_target_issue(REPLY, inbox_rows=[row("m1", 10)], sent_rows=None)[0] == \
        "reply_target_unverified"
    assert reply_target_issue(REPLY, inbox_rows=[], sent_rows=[])[0] == "reply_target_unverified"
    assert reply_target_issue({**REPLY, "email_id": ""}, inbox_rows=[row("m1", 10)], sent_rows=[])[0] == \
        "reply_target_missing"
