# Scriba reuse matrix: automation, desktop agent, files

Written 14 November 2026 from a read-only checkout of ScribaAssist/Scriba at
`3ae3a2a` (directory `Gmail/`). Nothing in Scriba was changed, and **no Scriba
source is copied into this repository**: the Desk imports Scriba's modules from
the checkout it runs on (`SCRIBA_BACKEND_PATH`), as it already did. This file
names modules, functions and signatures so that the integration can be checked;
it reproduces no implementation.

How it was produced: three read-only passes over the source (automation engine, desktop agent,
files and documents). Every function the Desk calls (section 1) was then imported and exercised
here; sections 2 and 3 are what the audit found and were not all re-verified by hand.

Paths are relative to `Gmail/`. "In process" means: importable and callable
from the Desk overlay with no database and no network.

## 1. What the Desk now calls

| Capability | Scriba module and callable | In process | Scriba's own tests | How the Desk calls it | Adaptation in the Desk | Safety |
| --- | --- | --- | --- | --- | --- | --- |
| Type of a file, by its bytes; programs and renamed files refused | `app/chat_files.py` `detect(filename, content)` | Yes | `tests/test_chat_files.py` | `desk_overlay/files.py` `inspect` | Maps `ChatFileError.code` to a read result instead of an HTTP error | 25 MB bound (Scriba's own for an attached file) |
| Reading PDF, Word, Excel, PowerPoint, CSV, text | `app/document_intelligence.py` `extract(content, *, kind, extension, filename, allow_ocr)` | Yes (OCR needs a binary or a network call: switched off) | `tests/test_document_intelligence.py`, `test_document_limits.py` | `files.read` | Keeps 20,000 characters for planning; never stores file text in a run | Scriba's zip-bomb and size guards apply; scanned pages reported as not read |
| Exact figures over every row of a sheet, streamed | `app/chat_table_query.py` `run_query(content, *, kind, extension, tool_input)` | Yes | `tests/test_chat_table_query.py` | `files.sheet_figures` | One query per column (count, sum, avg, min, max) | Scriba's bounds (200k rows, 4M cells, 25 s): past one, no totals are returned and the column is reported as not measured |
| Text written to an assistant inside a file | `app/services/content_guard.py` `scan_untrusted_text(text)` | Yes | `tests/test_content_guard.py` | `files.read` | A finding holds the whole run (`untrusted_instructions`, `source: "attachment"`) | The file is not summarised and is never passed to a model |
| Word document generation, with approval | Chat tool `create_document`: `app/chat_file_tools.py` `validate_document`, `approve_document`; `app/services/document_service.py` `build_docx_bytes(content)` | Generator yes; storage needs the database | `tests/test_chat_file_tools.py`, `test_docx_actions.py` | The Desk proposes Scriba's own card (`gateway.propose_action`) and Scriba's approve route runs it | Added to the Desk's chat tool scope and to the internal-write tools | Approval required; writes only the person's own records |
| Workbook generation, with approval | Chat tool `create_spreadsheet`: `chat_file_tools.approve_spreadsheet`, `build_xlsx(sheets)` | Same | `tests/test_chat_spreadsheet_formats.py`, `test_chat_xlsx_formulas.py` | Same path; in scope, not yet planned by the Desk's rules | Same | Same |
| Where a generated file is kept | `app/services/document_service.py` `store_generated_document(...)` | No (database and disk) | `tests/test_chat_file_tools.py` | Called by Scriba itself; in a sandbox world the execution gate routes it to the world | `execution.py` seam, like the existing provider seams | In a sandbox: no disk, no database, no cloud storage |
| Changing a workbook: one cell, a row by header, a row matched on a key; with backup, read-back of the written cells, formula and sheet check, restore | `desktop_agent/skills/registry.py` `run_job(job, ctx)` with `SkillContext(allowed_roots=[...])`; skills `xlsx.update_cell`, `xlsx.append_row`, `xlsx.upsert_row` (`desktop_agent/skills/excel.py`) | Yes (they work on a file path; no device, no database) | `tests/test_agent_excel_writer.py`, `test_agent_xlsx_actions.py`, `test_agent_sheet_hardening.py` (not re-run here) | `desk_overlay/workbooks.py` `apply`: a copy in a temporary folder that is the skills' only allowed root, removed afterwards | Operations validated first (no formula-like value); all or nothing; the result reopened with Scriba's reader and compared with the original; kept as a new file | The original is never touched; the person applies each change; nothing is written outside the temporary folder |
| Card creation, validation, atomic approve, retry, cancel | `app/chat_service.py` (already used by the Desk) | With the in-memory chat store | `tests/test_contract_chat_tool_lifecycle.py` | Unchanged | None | Unchanged: approval gate, binding, idempotency |
| Desktop subsystem switch | `app/desktop_security.py` `desktop_enabled() -> (bool, reason)` | Yes | `tests/test_kill_switch_choke_points.py` | `desk_overlay/desktop.py` `ScribaDesktop.enabled` | None | Off by default (`DESKTOP_AGENT_ENABLED`), kill switch honoured |
| Paired devices and their readiness | `app/services/desktop_agent_service.py` `list_user_agents(user_id)`; `app/desktop_device_state.py` `device_readiness` | No (database) | `tests/test_desktop_release_and_compat.py` | `ScribaDesktop.devices` | `device_view`: adds `canRunRecordedTasks` | Per user; a browser-extension device cannot take a desktop task |
| Recorded tasks | `app/services/desktop_recording_service.py` `list_all(*, user_id)` | No | `tests/test_desktop_recordings.py` | `ScribaDesktop.recordings` | `task_view`: never returns steps | Steps can hold typed text: they do not leave the bridge |
| Queue a replay | `desktop_recording_service.replay(*, user_id, recording_id, agent_id=None, ...)` | No | `tests/test_desktop_recordings.py`, `test_recordings_that_submit.py` | `DesktopBridge.assign` | Requires an explicit `confirm` and a ready device first | Scriba's gates stay: device online and unlocked, committing clicks wait on the device, replay confined to recorded apps |
| Follow, cancel, audit a job | `app/services/desktop_job_service.py` `get_job`, `cancel_job`; `app/desktop_repository.py` `list_audit` | No | `tests/test_desktop_replay_status.py`, `test_desktop_cancel_routes.py` | `DesktopBridge.job`, `.cancel` | `job_state`: reads the record as what it proves (section 3) | A stale replay is `OUTCOME_UNKNOWN`, not "failed, try again" |

## 2. Inspected and not integrated, with the reason

| Scriba capability | Where | Why not (yet) |
| --- | --- | --- |
| Automation engine: plans, steps, triggers, risk | `packages/domain/automation_definitions/engine.py` (`validate_plan`, `plan_run`, `run_steps`, `compute_risk`, `build_shadow_preview`, `trigger_matches`): pure, importable | The Desk already has one run lifecycle with approval binding, verification and recovery. Running a second engine beside it is the parallel system the brief forbids. The pure validators are the right next reuse: validate and risk-score a Desk plan with Scriba's own `validate_plan` and `compute_risk`. Not done |
| Natural-language automation creation | `app/automation_planner.py` `draft_plan_from_text` | Needs a model; behind `DESKTOP_AGENT_ENABLED` on the HTTP route. Callable in process. Not wired: the Desk's planner covers the inbox job, and this would add a second planner |
| Run service: run, approve, retry, undo, receipts | `app/services/automation_run_service.py`, `automation_action_receipts` | Needs Postgres (or the test-only `InMemoryDesktopRepo`). Not available in this environment |
| Triggers and schedules | `app/automation_triggers_domain_adapter.py`, `app/services/schedule_service.py`, `app/schedule.py` | The Desk's intake worker already claims each message once. Scriba's scheduler needs the database |
| Desktop file skills other than the three workbook edits: `xlsx.backup_file`, `docx.create`, `docx.append` | `desktop_agent/skills/`, dispatched by `skills/registry.py` `run_job(job, ctx)` | The three workbook edits are integrated (section 1). Word files are generated through Scriba's `create_document` card instead, which has an approval; appending to an existing Word file is not integrated |
| Table transformation | `desktop_agent/table_engine.py` `transform_workbook`; `app/services/server_table_service.py` | Same: reusable on a file path; not integrated |
| Teach-once extraction | `app/teach_extract.py` `extract_batch` | Pure without a model. No Desk workflow needs it yet |
| Document question answering by a model | `app/llm_client.py` `summarize_document_text` (feature `document_qa`) | Needs a model. The Desk's review is rule-based and says so. A model-written summary is a later, labelled option |
| Reading a real mailbox's attachments | `app/attachments.py` `collect_message_attachments` (Gmail), `app/outlook_client.py` `fetch_message_attachments`, `apps/api/email_read.py` | Needs the database and provider tokens. **The Desk reads attachments only in a sandbox world today.** On a real mailbox `gateway.attachments` returns `None` and nothing is claimed |
| Malware scan | `app/malware_scan.py` `scan(content)` | Needs a ClamAV daemon. Scriba itself does not scan email attachments (only chat uploads and Slack files). The Desk reports no scan; it relies on type-by-bytes, blocked executables and never executing a file |
| Chat uploads, cloud drives | `app/chat_files.py` `upload`, Drive and OneDrive tools | Uploading and sharing stay out of the Desk's tool scope |

## 3. What does not exist in Scriba (so it was not reused, and not invented)

| Asked for | Finding |
| --- | --- |
| Presentation generation | **No PowerPoint generator exists** in Scriba at `3ae3a2a`; `python-pptx` is not a dependency. Scriba reads `.pptx` (stdlib XML) and does not write it. The Desk does not generate presentations |
| PDF or CSV generation | Not found |
| Resuming an interrupted recorded task | **Not found.** The agent keeps no checkpoint for a replay (`desktop_rpa/player.py`, `desktop_agent/rpa_jobs.py`); only file-skill jobs have write-ahead receipts. The bridge reports `resume.supported: false` |
| Screenshots from the desktop | Not captured or sent by design (`desktop_rpa/README.md`) |
| An observe-act-verify loop in the player | Not in this revision: the player is linear, with click healing and end-of-run checks |
| Calendar actions in automations | Not in the automation vocabulary; calendar writes exist only in the chat action path, which the Desk already uses |

## 4. What must not be copied into this public repository

Everything under `Gmail/` is Scriba's. The Desk keeps to imports at run time.
In particular: the automation engine and planner prompts, the desktop agent and
its packaging, the recorder and player, provider clients, the database schema,
and any configuration or environment file. No secret, token, customer record
or internal configuration was read into this repository; the tests use
synthetic files built in memory.

## 5. Fastest safe path, as taken and as it continues

1. Done: readers, type check, table query and content scan behind `files.py`.
2. Done: Scriba's `create_document` and `create_spreadsheet` cards inside a Desk run, with verification by reopening.
3. Done: desktop bridge over Scriba's service functions, with a labelled fake.
4. Done (0.5.1): Scriba's `xlsx.*` skills on a copy (change a workbook, original preserved, result a new file).
5. Next: real-mailbox attachments through Scriba's stored attachments, on a backend with its database.
6. Next: `validate_plan` and `compute_risk` over Desk plans.
