"""The office is consistent and reproducible; every day profile is well formed."""
import copy
import json
import re

import pytest

from officesim import oracle, scenarios
from officesim.fakes import empty_world
from officesim.jobmodel import ASSUMED_HUMAN_MINUTES, JOB_STEPS, STEP_IDS
from officesim.office import (DEFAULT_DAY, OfficeClock, build_office, fingerprint, own_addresses,
                              people_by_email, person)

TIME_REF = re.compile(r"^D[+-]\d+ \d\d:\d\d$")


def test_same_seed_same_office():
    assert build_office(DEFAULT_DAY, 7) == build_office(DEFAULT_DAY, 7)
    assert build_office(DEFAULT_DAY, 7)["fingerprint"] == build_office(DEFAULT_DAY, 7)["fingerprint"]


def test_fingerprint_covers_the_content(spec):
    changed = copy.deepcopy(spec)
    changed.pop("fingerprint")
    changed["calendar"][0]["start"] = "2026-11-16T09:15:00+01:00"
    assert fingerprint(changed) != spec["fingerprint"]


def test_another_week_moves_every_date():
    later = build_office("2026-11-23", 7)
    assert later["calendar"][0]["start"].startswith("2026-11-23")
    with pytest.raises(ValueError):
        build_office("2026-11-17", 7)          # not a Monday


def test_only_reserved_example_domains(spec):
    text = json.dumps(spec)
    for found in set(re.findall(r"[\w.+-]+@([\w.-]+)", text)):
        assert found.endswith(".example") or found == "example.com", found


def test_one_identity_per_person_and_no_stranger_on_the_calendar(spec):
    emails = [entry["email"] for entry in spec["people"]]
    ids = [entry["id"] for entry in spec["people"]]
    assert len(set(emails)) == len(emails) and len(set(ids)) == len(ids)
    known = set(people_by_email(spec)) | set(own_addresses(spec))
    for event in spec["calendar"]:
        for attendee in event["attendees"] + [event["organizer"]]:
            assert attendee in known, (event["id"], attendee)


def test_calendar_is_internally_consistent(spec):
    ids = [event["id"] for event in spec["calendar"]]
    assert len(set(ids)) == len(ids)
    accounts = set(spec["accounts"]["gmail"]) | {spec["accounts"]["outlook"]}
    for event in spec["calendar"]:
        assert event["account"] in accounts
        assert oracle.parse(event["end"]) > oracle.parse(event["start"])
        assert (event["provider"] == "outlook") == (event["account"] == spec["accounts"]["outlook"])
    # The office starts with no double booking, so any later one is the Desk's.
    world = empty_world(spec)
    for event in world["events"]:
        assert oracle.is_free(world, oracle.parse(event["start"]), oracle.parse(event["end"]), [event["id"]])


def test_awaited_replies_have_the_message_they_wait_on(spec):
    threads = {row["thread_id"]: row for row in spec["sent"]}
    for follow in spec["followUps"]:
        assert follow["threadId"] in threads
        assert follow["waitingOn"]["email"] in threads[follow["threadId"]]["to"]


def test_job_model_has_ten_steps():
    assert len(JOB_STEPS) == 10 and [s["n"] for s in JOB_STEPS] == [str(n) for n in range(1, 11)]
    assert all(value > 0 for value in ASSUMED_HUMAN_MINUTES.values())


@pytest.mark.parametrize("profile_id", list(scenarios.PROFILES))
def test_profile_is_well_formed(profile_id, spec):
    profile = scenarios.build(profile_id)
    clock = OfficeClock(spec["day"], spec["timezone"])
    world = empty_world(spec)
    seen, previous = set(), None
    assert profile["steps"][-1]["kind"] == "briefing"
    for step in profile["steps"]:
        assert TIME_REF.match(step["at"]), step["at"]
        moment = oracle.ref_time(clock, step["at"])
        assert previous is None or moment >= previous, f"{step['id']} goes back in time"
        previous = moment
        assert set(step["job"]) <= set(STEP_IDS)
        for email in step["emails"]:
            assert email["id"] not in seen, f"duplicate message id {email['id']}"
            seen.add(email["id"])
            person(email["sender"])                       # a known person
            assert email["to"] in ("work", "advisory", "outlook")
            # The expectation can be resolved against the office.
            resolved = oracle.resolve(email["expect"], spec=spec, clock=clock, state=world, mailbox=email["to"])
            assert oracle.options_of(resolved) or resolved["outcome"] == "either"
            if email.get("human"):
                assert email["human"]["decision"] in ("reject", "edit") and email["human"]["why"]


def test_every_job_step_is_exercised_somewhere():
    used = {job for profile_id in scenarios.PROFILES for step in scenarios.build(profile_id)["steps"]
            for job in step["job"]}
    assert used == set(STEP_IDS)


def test_scenarios_never_carry_their_expectation_to_the_backend(spec):
    """What is delivered is the message, nothing else."""
    from officesim.adapter import DeskClient
    from officesim.fakes import FakeDesk
    from officesim.runner import Simulation

    profile = scenarios.build("normal")
    with FakeDesk(spec) as fake:
        Simulation(DeskClient(fake.base_url), spec, {**profile, "steps": profile["steps"][:2]}, seed=7).run()
        for wire in fake.delivered:
            assert set(wire) <= {"provider", "account", "message_id", "from_addr", "subject", "body",
                                 "thread_id", "received_at", "labels", "to"}
            assert "expect" not in json.dumps(wire)
