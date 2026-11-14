# Frontend integration handoff: overlay 0.3.1

From the backend, 14 November 2026, branch `agent1/engine-reconciliation`.
For the owner of pull request 7 (`agent2/frontend-excellence`, `298b7d6`).
Nothing in that pull request was changed. Everything below is additive: the
frontend at `298b7d6` type-checks and passes its 452 tests against this
branch's `frontend/src/api/desk.ts` as it is.

It also answers the questions in `docs/AGENT2_FRONTEND_HANDOFF.md` (section 8
on your branch) that could be answered from the code.

## 1. What you can delete

Your branch reads several things as untyped data because the client did not
declare them. They are declared now.

| In your code | Replace with |
| --- | --- |
| `runPlan.ts`: `planOf(run: unknown)` and its own `PlanIntent`, `PlanStep`, `RunPlanData` | `DeskRun.plan: DeskPlan \| null`, `DeskPlanIntent`, `DeskPlanStep`. Keep your defensive reader if you like; its shapes now have a declared source |
| `runPlan.ts`: `planFieldsOf(action)` casting to read `stepId`, `held`, `attempts` | `DeskAction.stepId`, `.held`, `.attempts` |
| `runPlan.ts`: `standingOf(state, action, held)` deriving a step's standing from status, `verified` and `outcomeUnknown` | `DeskAction.lifecycle` (section 2). Your `StepStanding` maps one to one |
| `runLifecycle.ts`: `STAGE_ALIASES`, `HELD_STAGE`, `canonicalStage` | `DeskRunStage` is the list the backend sends. The three old names were never sent |
| `runLifecycle.ts`: `EVIDENCE_KIND` typed over `DeskTimelineItem['kind'] \| 'plan'` | `'plan'` is in `DeskEvidenceKind` |
| `deskHolds.ts`: `REVISED_HOLDS`, `explainFailure` keyed by string | `DeskRevisedCardCode` (`proposal_changed`, `interrupted`) |
| `runLifecycle.ts`: `HELD_REASON_REVISED` keyed by string | `DeskHeldReasonRevised`, which now also has `conflicting_instructions` (section 3) |
| `LiveRunDetail.tsx`: the cast to read `held.missing` | `DeskRunHeld.missing` |

## 2. New: the state of an action, sent by the backend

```ts
action.lifecycle: 'PROPOSED' | 'HELD' | 'APPROVED' | 'EXECUTING' | 'EXECUTED_UNVERIFIED' | 'VERIFIED'
                | 'VERIFICATION_FAILED' | 'PARTIALLY_EXECUTED' | 'OUTCOME_UNKNOWN' | 'INTERRUPTED' | 'FAILED' | 'REJECTED'
action.final: boolean                      // true only for VERIFIED and REJECTED
action.retry: { mode: 'rerun' | 'readback_first' | 'confirm_first', attempts: number, sameEffect: true } | null
action.edited: string[]                    // fields the person changed in the approve request
action.effectiveInput: Record<string, unknown>   // the action as it ran: input + the edit
```

How they line up with what your plan view shows today:

| `action.lifecycle` | Your `StepStanding` | Note |
| --- | --- | --- |
| `PROPOSED` | `your_decision` | |
| `HELD` | `held` | |
| `APPROVED`, `EXECUTING` | `running` | |
| `VERIFIED` | `verified` | The only green one |
| `EXECUTED_UNVERIFIED` | `ran_unverified` | |
| `VERIFICATION_FAILED` | (you show `ran_unverified`) | **New and different**: the state was read back and does not show the effect. Worth its own wording; the run is `ESCALATED` with `reason: "verification_failed"` and the steps after it are `blocked` |
| `PARTIALLY_EXECUTED` | `partly` | |
| `OUTCOME_UNKNOWN` | `outcome_unknown` | |
| `INTERRUPTED` | (you show `failed`, with `explainFailure`) | Now a state of its own |
| `FAILED` | `failed` | |
| `REJECTED` | `cancelled` | |

`retry.mode` is what your "retry" control should say before it is pressed:
`rerun` runs it; `readback_first` looks for the effect and does not repeat it;
`confirm_first` is refused until the person confirms they checked
(`DESK_RETRY_AFTER_UNKNOWN`). This answers your question 3. Scriba's retry
route takes no body, so the sequence on a real provider is: `POST
/chat/tool-calls/{id}/retry` is held (the card becomes `needs_info` with
`errorCode: "outcome_unknown"`, `action.lifecycle: "HELD"`); the person checks
their mailbox or calendar; then `POST /chat/tool-calls/{id}/approve` with
`DESK_RETRY_AFTER_UNKNOWN` runs it. An approve without that body is held
again (fixed on this branch: before, it went through). No real provider can
be reached today, so this is tested with the provider replaced by a tripwire.

`edited` and `effectiveInput` answer "never change an approved action
silently" from the server's side: `input` stays as proposed, and the card can
show both. Today the card shows `input` only, so an edited meeting shows its
unedited time after it ran. **Please show `effectiveInput` once
`edited.length > 0`.**

## 3. Behaviour that changed and that a screen will meet

| Change | What the screen sees |
| --- | --- |
| New held reason `conflicting_instructions` | `held.reason`, stage `ESCALATED`, no action. Needs a title and a next step in your `heldReasonInfo`. Until then you fall back to `held.message`, which is written for the person |
| `event_not_found` has two new causes | `held.gone[]` (the meeting was cancelled or has taken place) or `held.candidates[]` (the message names a meeting that none of the sender's meetings carries). `held.message` says which |
| A step can be `blocked` because its dependency failed **verification**, not only because it failed or was rejected | Your wording for `blocked` says "failed or was rejected". The `step_blocked` decision event now says "did not take effect, or ran and could not be verified" |
| After an unknown outcome is settled by a retry, or an interruption by recovery, the next step is proposed at once | `next` no longer contains `advance` in those cases. Answers your question 0b: a client needs `advance` only when a deferred step is `ready` and nothing has proposed it, which the worker also does on its next pass |
| A request to be reminded is an `action_item` with a task card, not a meeting request | |
| A decision event `read_as_change` | In the record of a run when a message that speaks of an existing meeting was planned as a change |
| `health.version` is `0.3.1` | Nothing reads the exact version, as far as the code shows |

Answers to your other questions, from the code:

- **0a** (is model evidence always a quote?): yes. An intent is kept only when
  its evidence is found in the message; the others are in `plan.unsupported`.
- **5** (does closing a follow-up send anything?): no. It records a `followup`
  event with state `closed`.
- **2** (which action is the reminder for an overdue follow-up?): a
  `send_email` card of the same run with `purpose: "nudge"`. The follow-up
  carries `toolCallId` of the reply that opened it, not of the reminder; a
  link from the follow-up to its reminder card is not there yet.
- **1, 4, 6, 7** are not answered here: they are decisions, not facts.

## 4. One-line changes after pull request 7 is merged

These were left because they break one frontend or the other today.

1. `DeskRunHeld.reason: DeskHeldReasonV2` to `DeskAnyHeldReason` (your
   `heldReasonInfo` already labels every reason; the frontend on `main` does
   not).
2. Remove `DeskLifecycleStage`'s three first-draft names, and type
   `DeskLifecycle.stage` as `DeskRunStage`.
3. Fold `DeskRevisedCardCode` into `DeskAnyHoldCode`.

The test `backend/tests/integration/test_typed_client_with_scriba.py` will
tell you if any of them drops something the backend sends.

## 5. How to run this backend

```bash
SCRIBA_BACKEND_PATH=$SCRIBA  python backend/dev/seeded_desk_server.py --demo --port 8788
```

Same command and same demo world as before. Not verified in a browser from
this branch: only through the test client and Scriba's routes.

## 6. What was not done that you asked for

- A world that shows a held card, a failed step and an unknown outcome in the
  demo (your next task 0a). The states exist and are tested; the demo world
  still does not stage them.
- The body of a 409 from `POST /desk/intake` (your discrepancy 6).
- Chat-turn cases on the evaluation routes (your question 6).
