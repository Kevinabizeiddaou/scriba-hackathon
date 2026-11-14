# For Agent 2: the integrated backend (overlay 0.5) and your frontend on `main`

From Agent 1, 14 November 2026, branch `agent1/integration`. Contract:
[../BACKEND_CONTRACT.md](../BACKEND_CONTRACT.md) sections 12 (0.4) and 13 (0.5).
The earlier checklists still apply: [AGENT2_INTEGRATION_HANDOFF.md](AGENT2_INTEGRATION_HANDOFF.md)
(0.3.1: action lifecycle, effective input, retry modes) and
[AGENT2_INTEGRATION_0_4.md](AGENT2_INTEGRATION_0_4.md) (commands, memory, task
updates, follow-up records). This page says what is true now.

## 1. State of the frontend against this backend

On the integration commit your frontend, as it is on `main`: type check
clean, **452 of 452 tests**, build passes.

## 2. What I changed in your files, and why (please review the wording)

I kept this to what the integrated backend needed to pass together with the
frontend. Nothing else in `frontend/` was touched.

| File | Change |
| --- | --- |
| `frontend/src/api/desk.ts` | The reconciliation's typed client, plus what 0.4 and 0.5 send: `DeskRun.kind`, `.command`, `.assistantMessage`, `.unresolved`; `DeskAction.target`, `.followUpId`; purpose `notify`; trigger `chat`; the follow-up fields; the new held reasons; `DeskMemory`; `postDeskCommand`, `getDeskMemory`. Additive: no union you build an exhaustive `Record` over was widened |
| `frontend/src/live/runLifecycle.ts` | `HELD_REASON_REVISED` gained six entries (`conflicting_instructions`, `needs_review`, `reply_needs_author`, `already_in_progress`, `already_handled`, `unresolved_requests`). New `FOLLOW_UP_STATE_REVISED` with `escalated`, read by `followUpInfo`. **The titles and "next" lines are my first draft** |
| `frontend/src/live/LiveFollowUps.tsx` | Escalated follow-ups get their own section instead of "State not recognised" |
| `frontend/src/live/deskRuns.test.ts` | The three tests that pin the text of `backend/desk_overlay/workflow.py` now pin the current backend: the run list carries `state` and `lifecycle`; `_DONE` is `executed` and `_PARTIAL` is `partially_executed`; held reasons are collected from where holds are set (a decision's `"reason"` is no longer mistaken for a hold) |

## 3. Reconciled shapes (what the backend sends, all declared and checked by a test)

| Topic | Field | Notes |
| --- | --- | --- |
| Plan | `DeskRun.plan` | `steps[].state`: `ready`, `waiting`, `blocked`, or the card's status; `steps[].pending` on a deferred step |
| Lifecycle stages | `lifecycle.stage` | The fifteen `DeskRunStage` values. `lifecycle.reason` new values: `unresolved_requests`, `task_completion_suggested`, `task_completed`, and the repeat reasons under `COMPLETED` |
| Held reasons | `held.reason` | `DeskAnyHeldReason`: now also `needs_review`, `reply_needs_author`, `already_in_progress`, `already_handled`, `conflicting_instructions` |
| Action lifecycle | `action.lifecycle`, `action.final` | Twelve named states; only `VERIFIED` and `REJECTED` are final |
| Effective input | `action.edited`, `action.effectiveInput` | What ran, or will run: show this, not `input`, once the person edited at approval |
| Retry modes | `action.retry` | `{mode, attempts, sameEffect}` or null |
| Follow-up records | `followUps[]` | `state` may be `escalated`; `nudges`, `nudgePending`, `source`, `reason` (`no_answer_after_reminder`, `holding_reply`), `lastHoldingReplyAt` |
| Task updates | `taskUpdates[]` | `state`: `suggested`, `completed`, `unverified`, `failed`, `dismissed` |
| Chat commands | `kind: "command"`, `command`, `assistantMessage` | `POST /desk/commands` |
| **New in 0.5** | `unresolved[]`, `next: "resolve_unresolved"` | Below |

## 4. New in 0.5 for the UI

1. **Unresolved requests.** `DeskRun.unresolved: {id, text, why, resolved}[]`.
   While one is not resolved the run is `ESCALATED` with reason
   `unresolved_requests` and `next` contains `resolve_unresolved`. Show the
   sentences (`text`) with why (`needs_your_decision`, `names_an_address`,
   `second_scheduling_request`, `details_missing`, `reply_needs_author`,
   `possibly_same_as_open_task`, `not_recorded`), and a button "I have this"
   that calls `POST /desk/runs/{runId}/unresolved/resolve`. After it the run
   can complete.
2. **More runs need the person.** A message from a person that the rules
   cannot place is `ESCALATED` (`needs_review`) instead of done. Expect the
   "needs you" queue to be longer on a rules-only backend; that is intended.
3. **A holding reply.** A follow-up whose awaited person only acknowledged
   has `reason: "holding_reply"` and stays `waiting`. Worth a line on the
   card ("They wrote that it is still coming").
4. **`held.target` on `task_exists`** now carries `{taskId, title}` when the
   match was by content, not title.

Not shown anywhere in the frontend yet (none of it breaks anything):
`taskUpdates`, `unresolved`, command runs and `assistantMessage`,
`GET /desk/memory`, `overdueTasks` on the follow-ups listing.

## 5. Behaviour that changed since 0.4

- `needs_review` is reached more often (a sign-off "Thanks" no longer files
  a message; mail the classifier calls automated on a weak subject hint is
  read as a person's).
- A run with an executed booking can be `ESCALATED` (`unresolved_requests`)
  rather than `COMPLETED`. Treat it as "done, with something left for you".
- A second task for work that already has one is not proposed
  (`task_exists`, or `unresolved` with `possibly_same_as_open_task`).

## 6. Seeing it

```
SCRIBA_BACKEND_PATH=<scriba>/Gmail python backend/dev/seeded_desk_server.py --demo --port 8788
# then, with a real model configured and DESK_MODEL=on DESK_UNDERSTANDING=model DESK_AGENT=on:
python backend/dev/demo_path.py http://localhost:8788 <scriba>/Gmail/e2e/seeded_server.py
```

The demo script leaves runs in every state the UI has to show: a completed
three-step run, a run waiting for a response, and a satisfied follow-up.
