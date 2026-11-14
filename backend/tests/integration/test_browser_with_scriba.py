"""The browser as a tool of the Desk, on a real (headless, isolated) Chromium
against a synthetic supplier portal.

Real: the browser; Scriba's page-side player, step cleaner, risk lexicon and
content guard; Scriba's Excel skills and file readers; the Desk's run, cards
and approvals. Synthetic: the portal (``dev/supplier_portal.py``, on
127.0.0.1), its account, its reports, the mail and the workbook. No model.

Skipped where no Chromium is installed.
"""
import io
import os
import sys

import openpyxl
import pytest

from desk_overlay import browser, browser_cdp, errands

from .test_execution_with_scriba import ALICE, approve, get, post, sandbox_desk
from .test_files_with_scriba import mail_with
from .test_workbooks_with_scriba import apply as apply_change, budget, cells

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "dev"))
import supplier_portal as sp  # noqa: E402

pytestmark = pytest.mark.skipif(browser_cdp.find_binary() is None, reason="no Chromium on this machine")
ASK = ("Please download the latest quarterly report from the Northwind supplier portal, update the attached "
       "workbook with the new figures, and send the completed report to finance@client.example.")


@pytest.fixture(scope="module")
def sessions():
    found = browser.Sessions(os.environ["SCRIBA_BACKEND_PATH"])
    yield found
    found.stop()


@pytest.fixture()
def portal():
    site, stop = sp.start(with_lure=True)
    yield site
    stop()


def site_of(portal, **extra):
    return {"id": "site-1", "name": "Northwind supplier portal", "origin": portal.origin, "synthetic": True,
            "start": "/home", "signIn": {"path": "/login", "synthetic": True, "submit": "Sign in",
                                         "fields": {"Email": sp.ACCOUNT, "Password": sp.ACCOUNT_PASSWORD}}, **extra}


@pytest.fixture()
def on(sessions, portal):
    """A fresh session on the portal (a new owner each time: no cookie is shared between tests)."""
    owner = f"owner-{id(portal)}"
    session = sessions.session(owner, site_of(portal))
    yield session
    sessions.forget(owner)


FETCH = {"goal": "Latest report", "ops": [
    {"op": "open", "path": "/home"}, {"op": "follow", "name": "Reports"},
    {"op": "follow", "name": "quarterly report", "pick": "latest"},
    {"op": "read", "label": "Period", "name": "period"},
    {"op": "download", "name": "Download", "kind": "xlsx", "checksum": "SHA-256"}]}
PHONE = "+961 1 555 0199"
UPDATE = {"goal": "Update the phone number", "ops": [
    {"op": "open", "path": "/profile"}, {"op": "fill", "fields": {"Phone": PHONE}},
    {"op": "submit", "name": "Save changes", "expect": {"check": "text_present", "text": "Saved"},
     "readback": {"path": "/profile", "fields": {"Phone": PHONE}}}]}


def approved(session, task):
    return browser.binding(session.site, browser.validate(task)[0])


# ── the errand, inside a Desk run ────────────────────────────────────────────
def desk_with_portal(desk, portal, sessions, monkeypatch):
    monkeypatch.setattr(errands, "_sessions", lambda workflow: sessions)
    world = desk["world"]()
    world.add_site(name="Northwind supplier portal", origin=portal.origin, aliases=["supplier portal"], start="/home",
                   sign_in={"path": "/login", "submit": "Sign in",
                            "fields": {"Email": sp.ACCOUNT, "Password": sp.ACCOUNT_PASSWORD}},
                   reports={"entry": "quarterly report"})
    return world


def test_one_run_fetches_the_report_changes_the_workbook_and_sends_the_email_each_with_its_own_gate(
        sessions, portal, monkeypatch):
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk_with_portal(desk, portal, sessions, monkeypatch)
        source = budget()
        run = mail_with(desk, [{"filename": "budget.xlsx", "content": source}], body=ASK, subject="Q3 supplier report")

        # 1. The report was fetched without asking: that only reads.
        seen = run["browser"]
        assert seen["state"] == "VERIFIED" and seen["verified"] and seen["simulated"] and seen["modelCalls"] == 0
        assert [s["op"] for s in seen["steps"]] == ["open", "follow", "follow", "read", "download"]
        assert all(s["state"] == "done" for s in seen["steps"]) and seen["values"] == {"period": "Q3 2026"}
        [report] = seen["downloads"]
        assert report["sha256"] == portal.sha256("q3-2026") and report["checksum"] == "matches_the_page"
        fetched = desk["client"].get(f"{desk['prefix']}{report['download']['path']}")
        assert fetched.status_code == 200 and fetched.content == portal.files["q3-2026"]
        assert [e["path"] for e in portal.log if e["method"] == "POST"] == ["/login"] and portal.lure_hits == []

        # 2. The workbook change is suggested, not made; nothing is sent.
        [change] = run["fileChanges"]
        assert change["state"] == "suggested" and run["actions"] == [] and world.sent == []
        assert [(o["op"], o["values"]) for o in change["operations"]] == [
            ("upsert_row", {"Department": "Sales", "Actual": 1100}), ("upsert_row", {"Department": "Ops", "Actual": 520}),
            ("upsert_row", {"Department": "HR", "Actual": 310})]
        assert run["lifecycle"]["stage"] == "ESCALATED" and run["lifecycle"]["reason"] == "file_change_suggested"

        # 3. The person applies it: Scriba's Excel skills, on a copy, verified. Only then is the email proposed.
        done = apply_change(desk, change).json()
        assert done["fileChanges"][0]["state"] == "applied" and world.files[change["sourceFileId"]]["content"] == source
        result = world.files[done["fileChanges"][0]["resultFileId"]]["content"]
        assert cells(result) == [["Department", "Planned", "Actual"], ["Sales", 1000, 1100], ["Ops", 500, 520],
                                 ["HR", None, 310], ["Total", "=SUM(B2:B4)", "=SUM(C2:C4)"]]
        [email] = done["actions"]
        assert email["tool_name"] == "send_email" and email["purpose"] == "send_report" and world.sent == []
        assert email["input"]["to"] == "finance@client.example" and "Q3 2026" in email["input"]["body"]
        assert "budget (updated).xlsx" in email["input"]["body"] and "not attached" in email["input"]["body"]

        # 4. The address came from the message, not from the person: a plain approval is held.
        held = approve(desk, email)
        assert held["error"] == "unverified_recipient" and world.sent == []
        # The person confirms the address: sent once, in the sandbox, and verified.
        approve(desk, email, payload_overrides={"desk_confirmed_recipients": ["finance@client.example"]})
        final = get(desk, f"/runs/{run['runId']}").json()
        assert len(world.sent) == 1 and world.sent[0]["to"] == ["finance@client.example"]
        assert final["lifecycle"]["stage"] == "COMPLETED" and final["actions"][0]["lifecycle"] == "VERIFIED"
        kinds = [item["kind"] for item in final["timeline"]]
        assert kinds.index("browser") < kinds.index("file") < kinds.index("proposal")      # one record, in order
        # Doing it all again changes nothing: one fetch, one change, one email.
        again = post(desk, f"/runs/{run['runId']}/advance").json()
        assert len(again["actions"]) == 1 and len(again["fileChanges"]) == 1 and again["browser"]["attempts"] == 1


def test_a_site_that_was_not_authorised_is_never_opened(sessions, portal, monkeypatch):
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        monkeypatch.setattr(errands, "_sessions", lambda workflow: sessions)
        body = f"Please download the latest report from the vendor portal at {portal.origin}/reports and send it to me."
        run = mail_with(desk, [], body=body, subject="Vendor report")
        assert run.get("browser") is None and run["held"]["reason"] == "site_not_authorised"
        assert portal.log == [] and run["actions"] == [] and run["lifecycle"]["stage"] == "ESCALATED"


def test_a_report_the_workbook_has_no_columns_for_changes_nothing_and_says_so(sessions, portal, monkeypatch):
    book = openpyxl.Workbook()
    book.active.append(["Region", "Forecast"])
    book.active.append(["North", 1])
    out = io.BytesIO()
    book.save(out)
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        desk_with_portal(desk, portal, sessions, monkeypatch)
        run = mail_with(desk, [{"filename": "forecast.xlsx", "content": out.getvalue()}], body=ASK)
        assert run["browser"]["state"] == "VERIFIED" and run["fileChanges"] == [] and run["actions"] == []
        assert run["lifecycle"]["reason"] == "workbook_not_mapped"
        assert any(d["kind"] == "decision" and "was not changed" in d["summary"] for d in run["timeline"])


def test_a_file_that_does_not_verify_stops_the_run_before_anything_is_changed_or_sent(sessions, portal, monkeypatch):
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk_with_portal(desk, portal, sessions, monkeypatch)
        portal.fault("/files/", "truncate", times=5)
        run = mail_with(desk, [{"filename": "budget.xlsx", "content": budget()}], body=ASK)
        seen = run["browser"]
        assert seen["state"] == "FAILED" and seen["error"] == "download_not_verified" and seen["downloads"] == []
        assert seen["steps"][-1]["verification"] == {"verified": False, "reason": "not_a_readable_file"}
        assert run["fileChanges"] == [] and run["actions"] == [] and world.sent == []
        assert [f for f in world.files.values() if f["origin"] == "download"] == []
        assert run["lifecycle"]["stage"] == "ESCALATED" and run["lifecycle"]["reason"] == "browser_failed"
        assert len(portal.requests_for("/files/")) == 2                    # tried again once, not more


# ── reading: free, and only on the site ──────────────────────────────────────
def test_the_latest_report_is_found_by_what_the_page_says_not_where_things_are(on, portal):
    first = browser.run_task(on, FETCH)
    assert first["state"] == "VERIFIED" and first["steps"][2]["picked"]["name"] == "Q3 2026 quarterly report"
    portal.set(layout="b", delay_ms=250)           # other structure, other order, and the list arrives late
    second = browser.run_task(on, FETCH)
    assert second["state"] == "VERIFIED" and second["downloads"][0]["sha256"] == portal.sha256("q3-2026")
    assert second["steps"][1]["how"] == "kept_locator"           # the menu did not change: no second look needed
    assert len(portal.requests_for("/login", "POST")) == 1       # one sign-in for both tasks


def test_a_dialog_in_the_way_is_closed_only_by_a_button_that_only_closes(on, portal):
    portal.set(modal=True)
    done = browser.run_task(on, FETCH)
    assert done["state"] == "VERIFIED" and "closed_dialog:Announcement" in done["steps"][1]["recovered"]
    assert portal.requests_for("/subscribe", "POST") == []       # "Accept and subscribe" was never pressed


def test_a_decoy_on_another_site_and_a_password_prompt_are_not_followed(on, portal):
    portal.set(lure=portal.lure_origin)
    done = browser.run_task(on, FETCH)
    assert done["state"] == "VERIFIED" and done["downloads"][0]["from"].startswith(portal.origin)
    assert done["ignored"] == [{"name": "Download report (fast mirror)", "reason": "leads_to_another_site",
                                "origin": portal.lure_origin}]
    assert portal.lure_hits == [] and portal.requests_for("/verify-password", "POST") == []
    # Told outright to go there, it still cannot: the address is not the site's.
    assert browser.validate({"ops": [{"op": "open", "path": portal.lure_origin + "/x"}]})[1]
    assert on.page.goto.__self__.allow(portal.lure_origin + "/x") is False


def test_text_written_to_an_assistant_is_reported_and_changes_nothing(on, portal):
    portal.set(injection=True)
    done = browser.run_task(on, FETCH)
    assert done["state"] == "VERIFIED" and done["values"] == {"period": "Q3 2026"}
    assert {f["where"] for f in done["untrustedFindings"]} == {"visible", "hidden"}
    assert done["blockedOrigins"] == [] and [e["path"] for e in portal.log if e["method"] == "POST"] == ["/login"]
    # While such text is on the site, an approved change is not made either.
    held = browser.run_task(on, UPDATE, approval=approved(on, UPDATE))
    assert held["state"] == "HELD" and held["error"] == "untrusted_instructions"
    assert portal.requests_for("/profile", "POST") == [] and portal.profile["phone"] != PHONE


def test_a_value_on_another_page_of_a_table_is_found_with_the_pages_read_together(on, portal):
    task = {"ops": [{"op": "open", "path": "/invoices"},
                    {"op": "find_row", "table": "Invoices", "match": "INV-2026-0142", "name": "invoice"}]}
    done = browser.run_task(on, task)
    assert done["state"] == "COMPLETED" and done["values"]["invoice"]["Amount"] == str(sp.INVOICES[12]["amount"])
    assert done["steps"][1]["foundOn"] == "/invoices?page=3" and done["steps"][1]["pagesRead"] == 3
    missing = browser.run_task(on, {"ops": [task["ops"][0], {**task["ops"][1], "match": "INV-0000"}]})
    assert missing["state"] == "FAILED" and missing["error"] == "row_not_found" and "invoice" not in missing["values"]


def test_one_slow_answer_is_tried_again_and_a_site_that_stays_slow_is_reported(on, portal, monkeypatch):
    monkeypatch.setattr(browser, "NAVIGATION_SECONDS", 1.0)
    assert browser.run_task(on, {"ops": [{"op": "open", "path": "/home"}]})["state"] == "COMPLETED"
    portal.fault("/reports", "hang", seconds=2.5, times=1)
    done = browser.run_task(on, {"ops": [{"op": "open", "path": "/reports"}, {"op": "follow", "name": "quarterly report", "pick": "latest"}]})
    assert done["state"] == "COMPLETED" and done["steps"][0]["recovered"] == ["slow_page_tried_again"]
    portal.fault("/invoices", "hang", seconds=2.5, times=2)
    stuck = browser.run_task(on, {"ops": [{"op": "open", "path": "/invoices"}]})
    assert stuck["state"] == "INTERRUPTED" and stuck["error"] == "timeout" and stuck["stepsDone"] == 0


# ── changing: only what was approved, once ───────────────────────────────────
def test_nothing_is_filled_in_or_submitted_without_an_approval_of_exactly_that(on, portal):
    asked = browser.run_task(on, UPDATE)
    assert asked["state"] == "NEEDS_APPROVAL" and asked["steps"] == [] and portal.log == []
    assert asked["approval"]["fields"] == [{"label": "Phone", "value": PHONE}]
    assert asked["approval"]["buttons"] == ["Save changes"] and asked["approval"]["origin"] == portal.origin
    other = {**UPDATE, "ops": [UPDATE["ops"][0], {"op": "fill", "fields": {"Phone": "+1 900 000"}}, UPDATE["ops"][2]]}
    refused = browser.run_task(on, other, approval=approved(on, UPDATE))       # approved for another value
    assert refused["state"] == "NEEDS_APPROVAL" and portal.requests_for("/profile", "POST") == []

    done = browser.run_task(on, UPDATE, approval=approved(on, UPDATE))
    assert done["state"] == "VERIFIED" and portal.profile["phone"] == PHONE
    assert done["steps"][2]["verification"] == {"verified": True, "method": "read_back", "answered": True,
                                                "pressedAgain": False}
    assert len(portal.requests_for("/profile", "POST")) == 1


def test_a_reading_task_cannot_press_something_that_commits_and_a_password_is_never_typed(on, portal):
    sneaky = browser.run_task(on, {"ops": [{"op": "open", "path": "/profile"},
                                           {"op": "follow", "name": "Delete company profile"}]})
    assert sneaky["state"] == "NEEDS_APPROVAL" and sneaky["error"] == "would_commit"
    assert portal.requests_for("/profile/delete", "POST") == []
    portal.set(lure=portal.lure_origin)
    typed = {"ops": [{"op": "open", "path": "/reports/q3-2026"}, {"op": "fill", "fields": {"Password": "x"}},
                     {"op": "submit", "name": "Verify and download"}]}
    refused = browser.run_task(on, typed, approval=approved(on, typed))        # even when a person approved it
    assert refused["state"] == "FAILED" and refused["error"] == "password_field"
    assert portal.requests_for("/verify-password", "POST") == []


def test_a_submission_with_no_answer_is_read_back_and_never_sent_twice(on, portal):
    assert browser.run_task(on, {"ops": [{"op": "open", "path": "/home"}]})["state"] == "COMPLETED"
    portal.fault("/profile", "drop_after_write")
    done = browser.run_task(on, UPDATE, approval=approved(on, UPDATE))
    assert done["state"] == "VERIFIED" and portal.profile["phone"] == PHONE
    check = done["steps"][2]["verification"]
    assert check["answered"] is False and check["method"] == "read_back" and check["verified"] and not check["pressedAgain"]
    assert len(portal.requests_for("/profile", "POST")) == 1


def test_a_form_over_several_pages_is_completed_and_the_result_read_back(on, portal):
    task = {"goal": "Open a service request", "ops": [
        {"op": "open", "path": "/requests/new"},
        {"op": "fill", "fields": {"Category": "billing", "Subject": "Duplicate invoice INV-2026-0142"}},
        {"op": "submit", "name": "Continue", "expect": {"check": "text_present", "text": "step 2 of 3"}},
        {"op": "fill", "fields": {"Details": "Invoice 0142 was issued twice.", "Needed by": "2026-11-30"}},
        {"op": "submit", "name": "Continue", "expect": {"check": "text_present", "text": "review"}},
        {"op": "expect", "expect": {"check": "text_present", "text": "Duplicate invoice INV-2026-0142"}},
        {"op": "submit", "name": "Submit request", "expect": {"check": "text_present", "text": "Request received"},
         "readback": {"path": "/requests", "text": "Duplicate invoice INV-2026-0142"}}]}
    done = browser.run_task(on, task, approval=approved(on, task))
    assert done["state"] == "VERIFIED", done
    assert portal.requests == [{"reference": "SR-1001", "category": "billing",
                                "subject": "Duplicate invoice INV-2026-0142",
                                "details": "Invoice 0142 was issued twice.", "needed_by": "2026-11-30"}]
    assert len(portal.requests_for("/requests/submit", "POST")) == 1


def test_an_interrupted_task_is_taken_up_again_without_repeating_a_submission(sessions, portal):
    session = sessions.session("interrupted", site_of(portal))
    seen = []

    def record(step):
        seen.append(step)
        if step.get("state") == "submitting":
            pass
        elif step.get("op") == "submit":
            sessions.browser.kill()                    # the browser dies right after the submission went out

    first = browser.run_task(session, UPDATE, approval=approved(session, UPDATE), record=record)
    assert any(s.get("state") == "submitting" for s in seen) and portal.profile["phone"] == PHONE
    assert len(portal.requests_for("/profile", "POST")) == 1
    # Taken up again from the record: the submission is on it, so it is read back, not pressed.
    pressed = [s["index"] for s in seen if s.get("state") == "submitting"]
    again = browser.run_task(session, UPDATE, approval=approved(session, UPDATE), submitted=pressed)
    assert again["state"] == "VERIFIED" and again["steps"][2]["verification"]["method"] == "read_back"
    assert len(portal.requests_for("/profile", "POST")) == 1 and first["state"] in ("VERIFIED", "INTERRUPTED")
    sessions.forget("interrupted")


def test_a_browser_that_dies_mid_errand_is_interrupted_and_a_new_attempt_finishes(sessions, portal):
    session = sessions.session("dies", site_of(portal))

    def record(step):
        if step.get("op") == "follow" and step.get("index") == 2:
            sessions.browser.kill()

    first = browser.run_task(session, FETCH, record=record)
    assert first["state"] == "INTERRUPTED" and first["downloads"] == [] and first["stepsDone"] == 2
    second = browser.run_task(session, FETCH)
    assert second["state"] == "VERIFIED" and len(second["downloads"]) == 1
    sessions.forget("dies")


# ── which sites ──────────────────────────────────────────────────────────────
@pytest.mark.parametrize("origin, sandbox, synthetic, ok", [
    ("http://127.0.0.1:8080", True, True, True),              # a synthetic site in a sandbox world
    ("http://127.0.0.1:8080", False, True, False),            # the same, on a real backend
    ("http://127.0.0.1:8080", True, False, False),            # loopback that is not marked synthetic
    ("http://localhost:8080", False, False, False),
    ("https://10.0.0.5", True, True, False),                  # a private network, even in a sandbox
    ("https://192.168.1.10", False, False, False),
    ("http://169.254.169.254", True, True, False),            # cloud metadata
    ("https://[::1]", False, False, False),
    ("https://user@example.com", False, False, False),
    ("https://example.com/path", False, False, False),
    ("file:///etc/passwd", True, True, False),
])
def test_an_internal_address_is_not_a_site(origin, sandbox, synthetic, ok):
    problems = browser.site_problems({"origin": origin, "synthetic": synthetic}, sandbox=sandbox)
    assert (problems == []) is ok, problems


def test_a_task_cannot_name_another_site_or_an_unknown_step():
    for ops in ([{"op": "open", "path": "https://evil.example/"}], [{"op": "open", "path": "//evil.example/x"}],
                [{"op": "run_script", "code": "x"}], [{"op": "follow"}], [],
                [{"op": "submit", "name": "Save", "readback": {"path": "https://evil.example"}}],
                [{"op": "fill", "fields": {"Phone": {"nested": 1}}}]):
        assert browser.validate({"ops": ops})[1], ops
    assert browser.binding({"origin": "https://a.example"}, browser.validate(UPDATE)[0]) \
        != browser.binding({"origin": "https://b.example"}, browser.validate(UPDATE)[0])
    assert browser.binding({"origin": "https://a.example"}, browser.validate(FETCH)[0]) is None
