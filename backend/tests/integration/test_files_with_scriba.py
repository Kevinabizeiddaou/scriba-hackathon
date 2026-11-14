"""Files through the Desk's run lifecycle, on Scriba's REAL machinery.

Real: Scriba's card creation and validation, its approve route, its own
``create_document`` / ``create_spreadsheet`` handlers and generators
(python-docx, openpyxl), its type check, readers, table query and
untrusted-content scan. Isolated: the generated file is kept in the sandbox
world instead of Scriba's database and disk. Every file here is synthetic and
exists only in memory.

No model, mailbox, calendar, cloud drive or desktop was involved.
"""
import pytest

from desk_overlay import files

from .test_execution_with_scriba import (ALICE, BOB, ORIGIN, SOFIA, approve, get, meeting, post, sandbox_desk,
                                         user_and_run)

DOCUMENT = {"title": "Review of budget.xlsx", "filename": "Review of budget.docx",
            "sections": [{"heading": "What was read", "paragraphs": ["One sheet, five rows."], "bullets": []},
                         {"heading": "What stands out", "paragraphs": [], "bullets": ["Ops, January: 5,200."]}]}


def propose(desk, run, tool_name, tool_input):
    user, desk_run = user_and_run(desk, run)
    with desk["registry"].using(desk["world"]()):
        return desk["workflow"]._propose(user, desk_run, {
            "tool_name": tool_name, "tool_input": tool_input, "purpose": "summarize_attachment",
            "reason": "A review of the attached file was asked for."})


def test_a_document_is_proposed_approved_generated_by_scriba_and_verified_by_reopening_it():
    with sandbox_desk() as desk:
        desk["sign_in"](ALICE)
        world = desk["world"]()
        run = meeting(desk)
        card = propose(desk, run, "create_document", DOCUMENT)
        assert card["status"] == "awaiting_approval", card
        assert world.files == {}                                   # nothing exists before the approval
        done = desk["client"].post(f"/chat/tool-calls/{card['id']}/approve", json={}, headers=ORIGIN).json()["tool_call"]
        assert done["status"] == "executed", done
        [stored] = [f for f in world.files.values() if f["origin"] == "generated"]
        assert stored["filename"].endswith(".docx") and stored["content"][:2] == b"PK"
        action = next(a for a in get(desk, f"/runs/{run['runId']}").json()["actions"] if a["toolCallId"] == card["id"])
        assert action["lifecycle"] == "VERIFIED" and action["verified"] is True
        assert action["verification"]["method"] == "file_reopened"
        # What Scriba's reader finds in the file is what was approved.
        reopened = files.read(stored["filename"], stored["content"])
        assert "Review of budget.xlsx" in reopened["text"] and "Ops, January: 5,200." in reopened["text"]
        assert [e["op"] for e in world.oplog if e["op"].startswith("document.")] == ["document.create"]
