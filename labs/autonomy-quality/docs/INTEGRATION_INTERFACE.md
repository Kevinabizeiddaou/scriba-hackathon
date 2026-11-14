# Integration interface: what the lab needs from the backend

For Agent 1. None of this is implemented by the lab inside `backend/`, and none of it is required for the lab to
run today. Each item says what the lab does instead, and what would improve if the backend offered it.

The lab talks to three surfaces of one running backend:

| Surface | Used for | Status |
| --- | --- | --- |
| `/desk/eval/v1` (contract 1.1.0): `GET /meta`, `POST /evaluation/runs`, `GET /runs/{id}`, `GET /approvals`, `POST /approvals/{id}/decision` | Starting a case, watching it, deciding approvals | Exists. Used exactly as documented |
| Product routes: `GET /desk/runs/{id}`, `POST /desk/intake`, `POST /desk/intake/sweep`, `POST /chat/tool-calls/{id}/approve\|cancel\|retry` | Reading `held`, `plan`, `timeline`; scenarios a person drives in the product (edit on approve, retry, duplicate intake) | Exists |
| `/lab/v1` (`server/lab_server.py`) | Reading the office back; building an office with several mailboxes; the outside world changing; two instrumented fault simulations | **Lab-side only.** Mounted by the lab's own launcher on the unmodified backend. Never in a product process |

## Requests, in order of value

### 1. Let a harness read the synthetic office (replaces most of the lab probe)

`GET /desk/eval/v1/runs/{id}/world`, read-only, visible to the run's owner:

```json
{
  "world": "case-...", "now": "...", "accounts": {"gmail": ["..."], "outlook": null},
  "events":     [{"id", "provider", "account", "title", "start", "end", "attendees", "organizer", "status"}],
  "sent":       [{"id", "provider", "provider_account_id", "to", "subject", "text", "thread_id", "in_reply_to"}],
  "drafts": [], "tasks": [], "reminders": [], "followUps": [],
  "operations": [{"seq", "op", "status", "object_id", "error"}],
  "isolationViolations": []
}
```

Why: the contract reports what the engine says it did. `run.sandbox.operations` is a count. A harness that wants to
check that the event exists, at that time, with those people, from that account, has nothing to check it against.
Today the lab reads `SandboxWorld` from inside the process through its own route. With this route Agent 2's runner
could check state too, and its `state` assertions would stop resting on the trace.

`SandboxWorld.snapshot()` already exists and holds the counts and the operation log; this is the same thing with
the rows.

### 2. Answer a decision that a guard refuses (defect, see handoff item D1)

`POST /approvals/{id}/decision` returns HTTP 500 when the approve is held by a guard. The lab treats a 5xx as a
failed check (`no_server_error`) and still verifies that nothing executed. Wanted: 200 with the approval and an
error code, or 409 with the code.

### 3. Come to rest without a client (defect, see handoff item D2)

After a read-back reconciles an unknown outcome, the run shows `next: ["advance"]` and the evaluation contract has
no such call. Wanted: the backend proposes the follow-on step itself, as it does after a normal execution. If a
client call must exist, add `POST /desk/eval/v1/runs/{id}/advance`.

### 4. Say why a run is held, on the evaluation run itself

A held card "is not offered as an approval" (contract section 10), so the evaluation run shows an action `skipped`
and outcome `escalated` with no reason. The lab reads `held.reason` and the card's `error_code` from
`GET /desk/runs/{deskRunId}`, and it knows `deskRunId` only through the probe. Wanted on the evaluation `AgentRun`:
`deskRunId`, `held: {reason, ...}`, and per skipped action the `errorCode`. They can sit beside `lifecycle`, which
is already added beyond the contract.

### 5. More of the office in `context` (optional)

Things the lab can only build through `/lab/v1/office` today:

| Wanted in `context` | For |
| --- | --- |
| `mailboxes: {gmail: [..], outlook: ".."}` and `input.email.mailbox` | A request reaching another of the executive's accounts |
| `calendar[].provider`, `calendar[].account`, `calendar[].organizer` | A calendar on a second provider; a meeting the executive does not organize. Today `build_world` makes every event a Google event organized by the principal |
| `faults[].mode: "uncertain"` documented | It already works (`SandboxWorld.FAULT_MODES`); contract 1.1.0 lists only `fail_times` and `fail_always` |
| `unreadableCalendars` documented in the contract table | It is in section 10 as "beyond the contract" |

### 6. Identify what is being measured

| Wanted | Today |
| --- | --- |
| `meta.desk.commit`: the hackathon commit the process was started from | Not reported. The lab reads `git rev-parse HEAD` of the checkout it was pointed at, and reports `backendDirty` |
| `meta.desk.model.name` (and `understanding`, `agentStep`) when a model is configured | `model.configured` is a boolean. A real-model result must name its model to be traceable |
| `health.scribaCommit` | `null` on the seeded backend |

### 7. Conversation input

Known (`conversation_input_unsupported`). The lab sends its four chat cases anyway, records the backend's own
refusal, and counts them as not completed in every denominator.

## The two instrumented routes

`POST /lab/v1/cards/{id}/tamper` and `POST /lab/v1/cards/{id}/interrupt` change stored state (a card's input; a
card left `executing`) because no public route can produce those conditions. They are used by seven cases, each of
which records `instrumented` in its result. They test guards Agent 1 already unit-tests (`proposal_changed`,
`recover_stale`) from the outside. If the backend prefers, it can offer the same two conditions as evaluation
faults (`context.faults: [{tool, mode: "changed_after_proposal" | "interrupted"}]`) and the lab will drop its
routes.
