"""Changing a workbook that came with a message: suggested, applied by the
person, carried out by Scriba's own Excel skills on a copy, verified, and kept
as a new file.

Real: Scriba's skills (backup, write, read-back, formula check, restore), its
type check and its reader. Isolated: the files live in a sandbox world; the
skills work in a temporary folder that is removed afterwards. Every workbook
here is synthetic. No model, mailbox, cloud drive or desktop was involved.
"""
import io

import openpyxl
import pytest

from desk_overlay import files, workbooks

from .test_execution_with_scriba import ALICE, BOB, ORIGIN, get, post, sandbox_desk
from .test_files_with_scriba import mail_with


def budget():
    """A workbook with a bold header, a totals row of formulas and a second sheet."""
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Budget"
    for row in (["Department", "Planned", "Actual"], ["Sales", 1000, 1040], ["Ops", 500, 5200],
                ["Total", "=SUM(B2:B3)", "=SUM(C2:C3)"]):
        sheet.append(row)
    sheet["A1"].font = openpyxl.styles.Font(bold=True)
    book.create_sheet("Notes").append(["Prepared by finance. Do not change."])
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def cells(content, sheet="Budget"):
    return [[c.value for c in row] for row in openpyxl.load_workbook(io.BytesIO(content))[sheet].iter_rows()]


def opened(desk, content=None):
    run = mail_with(desk, [{"filename": "budget.xlsx", "content": content or budget()}],
                    body="For your information, the budget workbook is attached.", subject="Budget workbook")
    return run, run["attachments"][0]["id"]


def suggest(desk, run, file_id, operations):
    return post(desk, f"/runs/{run['runId']}/file-changes", json={"fileId": file_id, "operations": operations})


def apply(desk, change):
    """Follow the path the run gives for applying a change, exactly as a client would."""
    return desk["client"].post(f"{desk['prefix']}{change['apply']['path']}", headers=ORIGIN)


OPS = [{"op": "update_cell", "sheet": "Budget", "cell": "C3", "value": 520},
       {"op": "append_row", "sheet": "Budget", "values": {"Department": "HR", "Planned": 300, "Actual": 310}},
       {"op": "upsert_row", "sheet": "Budget", "key": "Department", "values": {"Department": "Sales", "Actual": 1100}}]


def test_a_change_is_suggested_then_applied_on_a_copy_verified_and_the_original_is_untouched():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        source = budget()
        run, file_id = opened(desk, source)

        suggested = suggest(desk, run, file_id, OPS)
        assert suggested.status_code == 200, suggested.text
        [change] = suggested.json()["fileChanges"]
        assert change["state"] == "suggested" and change["verified"] is False and change["operations"] == OPS
        assert suggested.json()["next"] == ["apply_file_change"]
        assert suggested.json()["lifecycle"]["stage"] == "ESCALATED"
        assert suggested.json()["lifecycle"]["reason"] == "file_change_suggested"
        assert [f for f in world.files.values() if f["origin"] == "generated"] == []        # nothing yet

        done = apply(desk, change).json()
        [applied] = done["fileChanges"]
        assert applied["state"] == "applied" and applied["verified"] is True
        assert applied["verification"]["method"] == "workbook_reopened" and applied["verification"]["rowsAdded"] == 1
        assert [s["verified"] for s in applied["steps"]] == [True, True, True]            # each of Scriba's own checks
        assert applied["steps"][0]["oldValue"] == 5200                                    # what it replaced is on record
        assert done["next"] == [] and done["lifecycle"]["stage"] == "COMPLETED"

        [made] = done["files"]
        assert made["filename"] == "budget (updated).xlsx" and made["verified"] is True and made["changeId"] == applied["id"]
        result = desk["client"].get(f"{desk['prefix']}{made['download']['path']}").content
        # The values asked for, the totals row still last with its range grown, formatting and the other sheet kept.
        assert cells(result) == [["Department", "Planned", "Actual"], ["Sales", 1000, 1100], ["Ops", 500, 520],
                                 ["HR", 300, 310], ["Total", "=SUM(B2:B4)", "=SUM(C2:C4)"]]
        book = openpyxl.load_workbook(io.BytesIO(result))
        assert book["Budget"]["A1"].font.bold is True and book.sheetnames == ["Budget", "Notes"]
        assert cells(result, "Notes") == [["Prepared by finance. Do not change."]]

        # The original is byte for byte what arrived.
        [original] = [f for f in world.files.values() if f["origin"] == "attachment"]
        assert original["content"] == source
        # Applying again, or suggesting the same change again, makes nothing new.
        assert len(post(desk, f"/runs/{run['runId']}/file-changes/{applied['id']}/apply").json()["files"]) == 1
        assert len(suggest(desk, run, file_id, OPS).json()["fileChanges"]) == 1
        assert len([f for f in world.files.values() if f["origin"] == "generated"]) == 1


def test_if_one_operation_fails_nothing_is_kept_and_the_answer_says_which():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        run, file_id = opened(desk)
        ops = [OPS[0], {"op": "update_cell", "sheet": "No such sheet", "cell": "A1", "value": 1}, OPS[1]]
        change = suggest(desk, run, file_id, ops).json()["fileChanges"][0]
        after = apply(desk, change).json()
        [failed] = after["fileChanges"]
        assert failed["state"] == "failed" and failed["failedAt"] == 2 and failed["verified"] is False
        assert "No such sheet" in failed["steps"][1]["error"] and len(failed["steps"]) == 2   # the third never ran
        assert "original is unchanged" in failed["message"]
        assert after["files"] == [] and [f for f in world.files.values() if f["origin"] == "generated"] == []
        assert after["lifecycle"]["stage"] == "ESCALATED" and after["lifecycle"]["reason"] == "file_change_failed"
        # A failed change is not applied by trying again: it has to be suggested anew.
        assert post(desk, f"/runs/{run['runId']}/file-changes/{failed['id']}/apply").status_code == 409


@pytest.mark.parametrize("operations, said", [
    ([{"op": "update_cell", "sheet": "Budget", "cell": "C3", "value": "=HYPERLINK(\"http://x.example\",\"x\")"}], "formula"),
    ([{"op": "update_cell", "sheet": "Budget", "cell": "C3", "value": "+cmd|' /C calc'!A0"}], "formula"),
    ([{"op": "update_cell", "sheet": "Budget", "cell": "../C3", "value": 1}], "cell must be"),
    ([{"op": "delete_sheet", "sheet": "Budget"}], "op must be"),
    ([{"op": "append_row", "sheet": "Budget", "values": {}}], "values must map"),
    ([{"op": "upsert_row", "sheet": "Budget", "key": "Region", "values": {"Department": "x"}}], "key must be"),
    ([{"op": "update_cell", "sheet": "Budget", "cell": "C3", "value": {"nested": 1}}], "must be text"),
    ([], "At least one"),
])
def test_an_operation_that_is_not_plain_data_is_refused_before_anything_is_recorded(operations, said):
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        run, file_id = opened(desk)
        refused = desk["client"].post(f"{desk['prefix']}/desk/runs/{run['runId']}/file-changes", headers=ORIGIN,
                                      json={"fileId": file_id, "operations": operations})
        assert refused.status_code in (400, 422), refused.text
        if refused.status_code == 400:
            assert said in refused.text
        assert get(desk, f"/runs/{run['runId']}").json()["fileChanges"] == []


def test_a_negative_number_and_ordinary_text_are_data():
    clean, problems = workbooks.validate([
        {"op": "update_cell", "sheet": "Budget", "cell": "c3", "value": -40},
        {"op": "update_cell", "sheet": "Budget", "cell": "A2", "value": "-40"},
        {"op": "update_cell", "sheet": "Budget", "cell": "A2", "value": "Sales - EMEA"},
        {"op": "update_cell", "sheet": "Budget", "cell": "A2", "value": None}])
    assert problems == [] and clean[0]["cell"] == "C3" and len(clean) == 4


def test_only_a_file_of_this_run_can_be_changed_and_only_by_its_owner():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        run, file_id = opened(desk)
        other = mail_with(desk, [{"filename": "other.xlsx", "content": budget()}], message_id="f2",
                          body="For your information, attached.", subject="Other workbook")
        # A file of another run is not this run's.
        assert suggest(desk, run, other["attachments"][0]["id"], OPS[:1]).status_code == 404
        assert suggest(desk, run, "no-such-file", OPS[:1]).status_code == 404
        change = suggest(desk, run, file_id, OPS[:1]).json()["fileChanges"][0]
        desk["sign_in"](BOB)
        assert desk["client"].post(f"{desk['prefix']}{change['apply']['path']}", headers=ORIGIN).status_code == 404
        desk["sign_in"](ALICE)
        assert get(desk, f"/runs/{run['runId']}").json()["fileChanges"][0]["state"] == "suggested"


def test_a_dismissed_change_does_nothing_and_cannot_be_applied_afterwards():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        run, file_id = opened(desk)
        change = suggest(desk, run, file_id, OPS[:1]).json()["fileChanges"][0]
        gone = post(desk, f"/runs/{run['runId']}/file-changes/{change['id']}/dismiss").json()
        assert gone["fileChanges"][0]["state"] == "dismissed" and gone["next"] == [] and gone["files"] == []
        assert apply(desk, change).status_code == 409
        assert [f for f in desk["world"]().files.values() if f["origin"] == "generated"] == []


def test_a_document_that_is_not_a_workbook_cannot_be_changed():
    from .test_files_with_scriba import letter

    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        run = mail_with(desk, [{"filename": "terms.docx", "content": letter(["Terms."])}],
                        body="For your information, attached.", subject="Terms")
        refused = suggest(desk, run, run["attachments"][0]["id"], OPS[:1])
        assert refused.status_code == 400 and "xlsx" in refused.text


def test_a_store_that_fails_or_does_not_confirm_is_never_reported_as_applied():
    from desk_overlay.sandbox import OP_CREATE_SPREADSHEET

    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        run, file_id = opened(desk)
        world.add_fault(OP_CREATE_SPREADSHEET, mode="fail_times", times=1)
        first = suggest(desk, run, file_id, OPS[:1]).json()["fileChanges"][0]
        failed = apply(desk, first).json()
        assert failed["fileChanges"][0]["state"] == "failed" and failed["fileChanges"][0]["error"] == "file_store_failed"
        assert failed["files"] == []

        world.add_fault(OP_CREATE_SPREADSHEET, mode="uncertain", times=1)
        second = suggest(desk, run, file_id, OPS[1:2]).json()["fileChanges"][-1]
        unsure = apply(desk, second).json()
        states = {c["id"]: c for c in unsure["fileChanges"]}
        assert states[second["id"]]["state"] == "unverified" and states[second["id"]]["verified"] is False
        assert unsure["files"] == []
        # A failed change outranks an unverified one, and neither lets the run read as done.
        assert unsure["lifecycle"]["stage"] == "ESCALATED" and unsure["lifecycle"]["reason"] == "file_change_failed"

        # The person sets both aside. That is recorded as what it was, never as applied.
        post(desk, f"/runs/{run['runId']}/file-changes/{first['id']}/dismiss")
        waiting = get(desk, f"/runs/{run['runId']}").json()
        assert (waiting["lifecycle"]["stage"], waiting["lifecycle"]["reason"]) == ("VERIFYING", "file_change_not_verified")
        after = post(desk, f"/runs/{run['runId']}/file-changes/{second['id']}/dismiss").json()
        seen = {c["id"]: c for c in after["fileChanges"]}
        assert (seen[first["id"]]["state"], seen[first["id"]]["dismissedFrom"]) == ("dismissed", "failed")
        assert (seen[second["id"]]["state"], seen[second["id"]]["dismissedFrom"]) == ("dismissed", "unverified")
        assert not any(c["verified"] for c in after["fileChanges"]) and after["files"] == []
        assert after["lifecycle"]["stage"] == "COMPLETED"
        assert apply(desk, first).status_code == 409


def test_an_applied_change_cannot_be_dismissed_and_applying_twice_keeps_one_file():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        run, file_id = opened(desk)
        change = suggest(desk, run, file_id, OPS[:1]).json()["fileChanges"][0]
        assert suggest(desk, run, file_id, OPS[:1]).json()["fileChanges"] == [change]     # asked twice: one suggestion
        once = apply(desk, change).json()
        again = apply(desk, change).json()
        assert [f["id"] for f in again["files"]] == [f["id"] for f in once["files"]] and len(once["files"]) == 1
        assert len([f for f in desk["world"]().files.values() if f["origin"] == "generated"]) == 1
        refused = post(desk, f"/runs/{run['runId']}/file-changes/{change['id']}/dismiss")
        assert refused.status_code == 409
        assert get(desk, f"/runs/{run['runId']}").json()["fileChanges"][0]["state"] == "applied"
        # The changed copy is itself a file of this run: it can be changed in turn, into a third file.
        nxt = suggest(desk, run, once["files"][0]["id"], OPS[1:2]).json()["fileChanges"][-1]
        third = apply(desk, nxt).json()
        assert [c["state"] for c in third["fileChanges"]] == ["applied", "applied"] and len(third["files"]) == 2


def test_a_result_that_lost_a_sheet_or_a_formula_is_not_verified():
    source = budget()
    good = workbooks.apply("budget.xlsx", source, [OPS[0]])
    assert good["ok"] and workbooks.verify("budget.xlsx", source, good["content"], [OPS[0]], good["steps"])["ok"]
    # The same change, but the result has lost its second sheet.
    book = openpyxl.load_workbook(io.BytesIO(good["content"]))
    del book["Notes"]
    out = io.BytesIO(); book.save(out)
    assert workbooks.verify("budget.xlsx", source, out.getvalue(), [OPS[0]], good["steps"])["reason"] == "sheets_differ"
    # ... or its totals formulas.
    book = openpyxl.load_workbook(io.BytesIO(good["content"]))
    book["Budget"]["B4"], book["Budget"]["C4"] = 1500, 1560
    out = io.BytesIO(); book.save(out)
    assert workbooks.verify("budget.xlsx", source, out.getvalue(), [OPS[0]], good["steps"])["reason"] == "formula_lost"
    # ... or has a row nobody asked for.
    book = openpyxl.load_workbook(io.BytesIO(good["content"]))
    book["Budget"].append(["Ghost", 1, 1])
    out = io.BytesIO(); book.save(out)
    assert workbooks.verify("budget.xlsx", source, out.getvalue(), [OPS[0]], good["steps"])["reason"] == "row_count_unexpected"
    assert workbooks.verify("budget.xlsx", source, source, [OPS[0]], good["steps"])["reason"] == "nothing_changed"


def test_the_skills_work_only_inside_their_own_folder_which_is_removed():
    import glob
    import tempfile

    before = set(glob.glob(tempfile.gettempdir() + "/desk-workbook-*"))
    done = workbooks.apply("budget.xlsx", budget(), [OPS[0]])
    assert done["ok"] and files.read("budget.xlsx", done["content"])["read"]
    assert set(glob.glob(tempfile.gettempdir() + "/desk-workbook-*")) == before       # nothing left behind
    assert workbooks.apply("notes.txt", b"plain text", [OPS[0]])["code"] == "not_a_workbook"


def test_too_many_operations_or_an_over_long_value_are_refused():
    def cell(n, value=1):
        return {"op": "update_cell", "sheet": "Budget", "cell": f"A{n}", "value": value}

    many = [cell(n) for n in range(1, workbooks.MAX_OPERATIONS + 2)]
    assert workbooks.validate(many) == ([], [f"At most {workbooks.MAX_OPERATIONS} operations can be applied at once."])
    assert workbooks.validate(many[:workbooks.MAX_OPERATIONS])[1] == []
    clean, problems = workbooks.validate([cell(2, "x" * (workbooks.MAX_TEXT + 1))])
    assert clean == [] and "longer than" in problems[0]
    assert workbooks.validate([cell(2, "x" * workbooks.MAX_TEXT)])[1] == []
    assert workbooks.validate([{"op": "format_cell", "sheet": "Budget", "cell": "A1", "value": 1}])[0] == []


def test_a_write_the_skill_did_not_verify_is_not_kept_and_the_skills_get_only_the_working_folder(monkeypatch):
    import os

    from desktop_agent.skills import registry

    real, seen = registry.run_job, []

    def not_verified(job, ctx):
        seen.append((job["payload"]["path"], [str(root) for root in ctx.allowed_roots]))
        outcome = real(job, ctx)
        outcome.result["verification"] = {**outcome.result["verification"], "verified": False}
        return outcome

    monkeypatch.setattr(registry, "run_job", not_verified)
    done = workbooks.apply("budget.xlsx", budget(), [OPS[0], OPS[1]])
    assert done["ok"] is False and done["code"] == "operation_failed" and done["failedAt"] == 1
    assert len(done["steps"]) == 1 and done["steps"][0]["status"] == "succeeded" and done["steps"][0]["verified"] is False
    assert "could not be verified" in done["message"] and "content" not in done
    [(path, roots)] = seen                                    # the second operation never ran
    assert len(roots) == 1 and os.path.dirname(path) == roots[0]
    assert os.path.basename(roots[0]).startswith("desk-workbook-") and not os.path.exists(roots[0])


def test_a_change_is_bound_to_the_file_and_the_operations_that_were_shown():
    import hashlib

    assert workbooks.binding("a", OPS) != workbooks.binding("b", OPS)
    assert workbooks.binding("a", OPS[:1]) != workbooks.binding("a", OPS[1:2])
    assert workbooks.binding("a", OPS) == workbooks.binding("a", [dict(op) for op in OPS])
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        run, file_id = opened(desk)
        change = suggest(desk, run, file_id, OPS[:1]).json()["fileChanges"][0]
        # The file is replaced after the change was shown: what was agreed to is no longer what would be changed.
        book = openpyxl.load_workbook(io.BytesIO(budget()))
        book["Budget"]["B2"] = 9999
        out = io.BytesIO()
        book.save(out)
        with world._lock:
            world.files[file_id].update(content=out.getvalue(), sha256=hashlib.sha256(out.getvalue()).hexdigest())
        after = apply(desk, change).json()
        [stale] = after["fileChanges"]
        assert stale["state"] == "failed" and stale["error"] == "change_no_longer_matches" and stale["verified"] is False
        assert after["files"] == [] and [f for f in world.files.values() if f["origin"] == "generated"] == []


def test_a_workbook_with_features_an_edit_would_drop_is_refused_by_scribas_skill_and_nothing_is_kept():
    import zipfile

    packed = io.BytesIO(budget())
    with zipfile.ZipFile(packed, "a") as archive:
        archive.writestr("customXml/item1.xml", "<data xmlns='urn:example'/>")
    content = packed.getvalue()
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        run, file_id = opened(desk, content)
        change = suggest(desk, run, file_id, OPS[:1]).json()["fileChanges"][0]
        after = apply(desk, change).json()
        [refused] = after["fileChanges"]
        assert refused["state"] == "failed" and refused["error"] == "operation_failed" and refused["failedAt"] == 1
        assert "custom XML" in refused["message"] and after["files"] == []
        assert world.files[file_id]["content"] == content


def test_a_result_that_cannot_be_read_is_not_verified():
    source = budget()
    good = workbooks.apply("budget.xlsx", source, [OPS[0]])
    assert workbooks.verify("budget.xlsx", source, b"not a workbook", [OPS[0]], good["steps"])["reason"] == "result_unreadable"
    assert workbooks.verify("budget.xlsx", b"not a workbook", good["content"], [OPS[0]], good["steps"])["reason"] == "original_unreadable"
    assert workbooks.verify("budget.xlsx", source, source, [OPS[0]], good["steps"])["reason"] == "nothing_changed"


def test_a_result_the_comparison_rejects_or_a_kept_file_that_differs_is_never_applied(monkeypatch):
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        run, file_id = opened(desk)
        assert post(desk, f"/runs/{run['runId']}/file-changes/fc-999-9/apply").status_code == 404
        # The skills report success and the reopened result does not match: it is not kept.
        monkeypatch.setattr(workbooks, "verify", lambda *a, **k: {"ok": False, "reason": "formula_lost", "sheet": "Budget"})
        first = suggest(desk, run, file_id, OPS[:1]).json()["fileChanges"][0]
        [bad] = apply(desk, first).json()["fileChanges"]
        assert bad["state"] == "failed" and bad["error"] == "result_not_verified" and bad["verified"] is False
        assert bad["verification"]["reason"] == "formula_lost"
        assert [f for f in world.files.values() if f["origin"] == "generated"] == []
        monkeypatch.undo()

        # The store answers yes and keeps something other than what it was given.
        keep = world.store_generated
        monkeypatch.setattr(world, "store_generated", lambda **kw: keep(**{**kw, "content": kw["content"] + b"extra"}))
        second = suggest(desk, run, file_id, OPS[1:2]).json()["fileChanges"][-1]
        odd = {c["id"]: c for c in apply(desk, second).json()["fileChanges"]}[second["id"]]
        assert odd["state"] == "unverified" and odd["error"] == "kept_file_differs" and odd["verified"] is False
