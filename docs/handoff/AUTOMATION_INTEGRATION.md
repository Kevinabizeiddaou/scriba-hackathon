# Automation integration: files, workbook changes and the desktop bridge (overlay 0.5.1)

Written 14 November 2026 on branch `agent1/automation-integration`, cut from
`main` at `30e0475`. For the project lead and Agents 2, 3 and 4.

**Nothing here is a result about a model, a real mailbox, a real calendar, a
cloud drive or a real computer.** Every run was in a sandbox world, rules
only, with synthetic files built in memory. No external write was made or is
possible. ScribaAssist/Scriba was read from a clone and not changed; none of
its source is in this repository.

Contract: [../BACKEND_CONTRACT.md](../BACKEND_CONTRACT.md) section 13.
What was reused and what was not: [SCRIBA_REUSE_MATRIX.md](SCRIBA_REUSE_MATRIX.md).

## 1. What works now

| Workflow | State |
| --- | --- |
| An email arrives with a file and asks for it to be looked at: read, review document, verification, then a reply for approval | **Works end to end in the sandbox**, including through the background worker and over HTTP on the demo backend |
| Scriba's `create_document` and `create_spreadsheet` inside a Desk run, with approval and verification by reopening the file | Works (`create_spreadsheet` is in scope; the Desk's rules do not plan one yet) |
| Changing a workbook of a run with Scriba's own Excel skills: suggested, applied by the person on a copy, verified by reopening, kept as a new file (0.5.1) | **Works in the sandbox.** The operations come from the caller; the Desk does not work out what to change, and no screen exists yet |
| Listing a person's paired computers and recorded tasks; queueing, following and cancelling a recorded task | Adapter written over Scriba's own functions and tested against their shapes. **No real device ran anything** |
| Everything the engine did before (meetings, changes, follow-ups, tasks, commands, memory) | Unchanged; all earlier tests pass |

Not built in this round: meeting-preparation
briefs, presentations (Scriba has no generator), a desktop task as a step of a
plan, model-written summaries, attachments of a real mailbox.

## 2. For Agent 2: what the screens need

Everything is typed in `frontend/src/api/desk.ts`; the frontend on `main`
type-checks and its 452 tests pass against it. Nothing in the frontend was
changed.

### 2.1 On the run page

| Data | Required behaviour |
| --- | --- |
| `run.attachments[]` | A "Files that came with this message" block: name, type, size, pages or sheets. `read: false`: say it was not read and why (`error`). `unreadParts > 0`: say scanned pages were not read. `untrustedFindings > 0`: say the file carries text written to an assistant and that nothing was proposed. Never show file content: the API does not send it |
| An action with `tool_name: "create_document"`, `purpose: "review_file"` | The card is Scriba's own. Show `input.title` and each section's heading, paragraphs and bullets: that is exactly what will be written. Label it as a write to the person's own records, not a send |
| `run.files[]` | A "Files the secretary made" block. Offer `download.path` as a download (fetch with credentials; the server always answers with `Content-Disposition: attachment`). **Show "verified" only when `verified` is true**; `state: "VERIFICATION_FAILED"` needs its own wording ("the file was written but does not show what was approved") |
| `verification.method: "file_reopened"` | Wording for your evidence line: "the file was opened again and shows what was approved" |
| The deferred `send_email` step with `purpose: "reply"` | It appears only after the review is verified. Its text quotes figures from the file: let the person edit it before approving |
| `held.reason: "untrusted_instructions"` with a decision whose `source` is `"attachment"` | Say the text was found **in a file**, and name the file from `evidence[]` |
| `simulated` on the run, the action and the file | Keep the Sandbox tag on all three |

### 2.2 A desktop screen

`GET /desk/desktop` never fails for "not connected": read `available`.

| State | Required behaviour |
| --- | --- |
| `available: false` | Show `message`, and nothing that looks runnable. `reason` distinguishes off (`desktop_agent_disabled`), nothing paired, nothing ready, and a sandbox with no device |
| `simulated: true` | A visible "simulated device" label on the device, every task and every job. It is a fake in a sandbox world |
| A task with `checks: 0` | Say before it is run that it can finish but cannot be verified |
| Starting a task | An explicit confirmation by the person, then `startDeskDesktopJob({recordingId, deviceId?, confirm: true})`. On 409 read the header `X-Desk-Error-Code` and show the body's message: nothing was queued |
| `DeskDesktopJob.state` | Ten states (contract 13.4). `ACCEPTED` is "queued, not started". Only `VERIFIED` is green. `SUCCEEDED_UNVERIFIED`, `NEEDS_REVIEW` and `OUTCOME_UNKNOWN` each need their own wording and none of them is success |
| `resume.supported: false` | Do not offer "resume". Offer "run again" as a new, confirmed job, and for `OUTCOME_UNKNOWN` say to check the computer first |
| Polling | Poll `GET /desk/desktop/jobs/{id}` while `final` is false. No push channel exists |

### 2.3 A change to a workbook (overlay 0.5.1)

Contract 13.5. The backend is there; no screen exists yet.

| Data | Required behaviour |
| --- | --- |
| A workbook in `run.attachments[]` or `run.files[]` (`kind: "xlsx"` or the workbook MIME type) | May offer "change this workbook". The person states the operations: cell and value, a row by column header, or a row matched on a key column. Send `suggestDeskFileChange(runId, {fileId, operations})`. On 400 show the body's `detail`: it names the operation and the reason. Nothing was recorded |
| `run.fileChanges[]` with `state: "suggested"` | Show every operation exactly as it will be applied (sheet, cell or row values), the file's name, and two actions: apply (`applyDeskFileChange`) and dismiss. Say that a changed COPY will be made and that the original stays as it is |
| `state: "applied"` | The only state that may read as done. Show `resultFilename` with its download (it is also in `run.files[]`, `changeId` set), and from `steps[]` what each operation changed (`cell`, `row`, `oldValue` or `oldValues`). Evidence wording for `verification.method: "workbook_reopened"`: "the changed copy was opened again and compared with the original" |
| `state: "failed"` | Show `message`. With `failedAt`, mark that operation and say the ones after it never ran. Say nothing was kept and the original is unchanged. Offer dismiss, and suggesting again |
| `state: "unverified"` | Its own wording: the store did not confirm, a copy may or may not exist. Never green. Offer dismiss |
| `state: "dismissed"` | Quiet. With `dismissedFrom` other than `suggested`, keep what it was visible ("set aside after it failed") |
| `lifecycle.reason` `file_change_suggested`, `file_change_failed`, `file_change_not_verified` | Three new reasons a run is not done. Each needs a line of wording |
| `next` contains `apply_file_change` | The run is waiting for the person on a change |
| Timeline items with `kind: "file"` | A new evidence kind (in `DeskRevisedEvidenceKind`): give it an icon and a label, or it falls through to your default |

### 2.4 Sample payloads

In the contract, 13.2 to 13.5. A live sample: start
`python backend/dev/seeded_desk_server.py --demo`; the message "Q4 budget
figures" carries a workbook, and the world has a fake computer with two
recorded tasks (one with a check, one without).

### 2.5 Known limitations a screen should not hide

Attachments of a real mailbox are not read (`health.files.attachments:
false`). A review is an extract by fixed rules and says so in its last
section. Presentations, PDFs and CSV files are not generated. A workbook
change is only what the person typed: nothing suggests which cells to change.

## 3. For Agent 3: what to attack

1. Reviews must contain only what is in the file. Try files whose figures or
   sentences would be easy to "improve": the oracle is that every number in
   the review is computable from the file and every quoted sentence is in it.
2. Injection in attachments: text written to an assistant in a cell, a
   comment, a header, a footnote, a hidden sheet, white-on-white, zero-width
   characters, a second language. Expected: held, nothing proposed. Detection
   is Scriba's `scan_untrusted_text`; what it misses is a finding. Whatever it
   misses still cannot act: a review only writes the person's own records and
   the reply needs approval.
3. Files that lie about their type; archives; very large and very wide
   sheets; a sheet past Scriba's bounds (expected: the column is "not
   measured", never a partial total).
4. The `VERIFIED` claim: make the store return success for a file that is
   wrong, truncated or of another type. Expected: `VERIFICATION_FAILED`, the
   reply blocked, the run `ESCALATED`.
5. Ordering: the reply must never be proposed before the review is verified,
   including across a retry, a rejection and a worker pass.
6. Cross-user: another account must get 404 for every file id and job id.
7. Desktop bridge: every job record shape you can construct must map to a
   state that claims no more than the record proves.
8. Workbook changes (contract 13.5). The oracles: the original's bytes never
   change; `applied` only when the kept file is the verified one; a failed
   operation keeps nothing; no value that a spreadsheet would evaluate is
   ever written. Try values that become formulas in ways the check does not
   know (a leading tab or line break, full-width `＝`, DDE strings, a very
   long number); workbooks with merged cells, tables, charts, pivots, data
   validation, macros, hidden or protected sheets, external links; headers
   that repeat or are empty; a key that matches two rows; a totals row that
   is not last; changing the result of a change; two applies at once.

## 4. For Agent 4: what the office can now use

A day can include a message with a workbook or a Word file
(`SandboxWorld.deliver(..., attachments=[{filename, content}])`), the review
it produces, and the approval-gated reply. `SandboxWorld.add_desktop(...)`
gives a world a fake computer whose jobs end as scripted (`pass`, `no_check`,
`needs_review`, `dialog`, `silent`). Both are simulated and must be reported
so. A simulated assistant or executive can now also ask for a workbook to be
changed (`POST /desk/runs/{id}/file-changes`, then apply): the operations
have to come from the simulation, the Desk does not derive them. Your earlier request A (clock, deliver, fault, tick, state over HTTP) is
still open.

## 5. Tests

Windows 11, Python 3.13, Node 22, Scriba read-only at `3ae3a2a`. Commit of
this branch: see the pull request. Execution mode: sandbox. Model: none
configured (`health.model.configured: false`); every result is rule-based.

| What | Result |
| --- | --- |
| Backend unit tests | 548 passed (unchanged from `main`) |
| Backend integration tests, on Scriba's real application | 330 passed, 56 skipped (real-model parameters). `main`: 274 |
| Of which new: files (12), desktop bridge (18), workbook changes (24), typed client (2) | All pass |
| Mutation check on the files and desktop code | 22 planted defects, 22 caught (20 at first; two tests added for "verified only by reopening") |
| Mutation check on the workbook-change code | 37 planted defects, 37 caught (26 at first; six tests added: limits, a write the skill did not verify, the working folder, the binding, a rejected comparison, a kept file that differs) |
| Frontend on this branch against the new typed client | Type check clean, 452 of 452 tests |
| Over HTTP on the seeded demo backend | Worker picked the file message up unasked; attachment read; review `VERIFIED` by `file_reopened`; file downloaded (37 kB, a real `.docx`); reply proposed, approved, sent in the sandbox; run `COMPLETED`. Desktop: fake device listed as simulated; a job without `confirm` refused (400); with it, `ACCEPTED` |

Scenario oracles (each is a test in `tests/integration/test_files_with_scriba.py`
or `test_desktop_with_scriba.py`): review totals equal the sums of the
workbook; quoted sentences are in the document; a file with text addressed to
an assistant yields no action; a program is not read; a message that only
carries a file gets no review; a rejected review blocks the reply; a wrong or
corrupt generated file is not verified and nothing follows; the original
attachment is byte for byte unchanged; another person gets 404; a 60,000-row
sheet gives exact totals; every desktop job record maps to a state that the
record proves. For workbook changes (`test_workbooks_with_scriba.py`): the
original is byte for byte unchanged in every outcome; a totals formula's
range grows with an appended row; one failed operation keeps nothing; a
formula-like value is refused before anything is recorded; a change applies
only to the file and operations that were shown; a workbook with features an
edit would drop is refused by Scriba's skill; a store that fails, does not
confirm or keeps other bytes is never reported as applied.

Not run: the quality lab and the office simulation against this branch; the
backend's own mutation list (`dev/mutation_check.py`) after these changes; any
real model; any real provider; any real device; a browser.

## 6. Cost and latency

No model was called, so there is no token count and no cost. In process, the
whole file workflow test (read, plan, approve twice, verify twice) takes about
half a second. A 60,000-row workbook is analysed in a few seconds with exact
totals. Over HTTP on the seeded backend each call showed about two seconds,
which is the seeded Scriba waiting for a database it does not have, not Desk
work. Nothing was measured on a real deployment.

## 7. Blockers and next, in order of value

1. **A screen for workbook changes** (Agent 2; section 2.3), and after it a
   way to derive the operations from a request ("set Ops actual to 520"):
   by rule for the plain cases, or by a model whose output is only ever a
   suggestion the person applies. Not built: today the caller sends them.
2. **Attachments of a real mailbox**, through Scriba's stored attachments: needs
   a backend with Scriba's database.
3. **A real device**: needs Postgres, `DESKTOP_AGENT_ENABLED`, a paired Windows
   agent and the lead's go-ahead. Until then the bridge is unverified against
   a device.
4. A desktop job as a step of a Desk plan, behind the same approval binding.
5. A model-written summary beside the rule-based extract, labelled, with the
   file passed as untrusted data, measured by Agent 3 before it is offered.
6. `validate_plan` and `compute_risk` from Scriba's engine over Desk plans.

Two other branches exist that this one does not include:
`agent1/integration` (another session's merge of the engine, three commits not
on `main`) and whatever Agents 3 and 4 pushed since. They were not merged or
changed.
