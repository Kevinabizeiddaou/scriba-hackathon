# For Agent 2: every frontend change that overlay 0.4 calls for

From Agent 1, 14 November 2026. Branch `agent1/autonomous-engine`. The
contract is [../BACKEND_CONTRACT.md](../BACKEND_CONTRACT.md), section 12; this
page is the checklist. I did not edit any frontend file, including
`frontend/src/api/desk.ts`: the types below are for you to add.

Everything is additive except the two items under "Behaviour that changed".
A client written against 0.3 keeps working; it just does not show the new
things.

## 1. Types to add to `frontend/src/api/desk.ts`

```ts
export type DeskRunKind = 'email' | 'command';
export type DeskTrigger = 'manual' | 'sweep' | 'worker' | 'evaluation' | 'chat';        // 'chat' is new
export type DeskNextStep = 'advance' | 'draft_reply' | 'complete_task';                 // 'complete_task' is new
export type DeskActionPurpose =
  | 'book' | 'reschedule' | 'cancel' | 'confirm' | 'offer_times' | 'clarify'
  | 'nudge' | 'reply' | 'record_task'
  | 'notify';                                                                           // new
export type DeskCommandOperation =
  | 'reminder' | 'task' | 'reschedule' | 'cancel' | 'notify' | 'chase_overdue';

export interface DeskTaskUpdate {
  taskId: string;
  title: string | null;
  op: 'complete';
  state: 'suggested' | 'completed' | 'dismissed' | 'failed';
  source?: 'rules' | 'model';
  matched?: string[];            // the words of the task's title found in the message
  verified?: boolean | null;     // true: a read-back no longer lists it as open
  by?: string;                   // 'policy', or the person's address
  error?: string | null;
  updatedAt: string;
}

export interface DeskEventTarget { id: string; title: string | null; start: string | null; end: string | null; provider: string | null }

// On DeskRun (all optional for older backends):
//   kind?: DeskRunKind
//   command?: { text: string; operations: DeskCommandOperation[] }      // command runs only
//   assistantMessage?: string                                            // command runs only
//   taskUpdates?: DeskTaskUpdate[]
// On DeskRun.email for a command run: email_id, thread_id and from_addr are null.
// On DeskAction:
//   target?: DeskEventTarget | null
//   followUpId?: string | null
// On DeskPlanStep:
//   pending?: Record<string, unknown> | null
// On DeskFollowUp:
//   kind?: 'reply'
//   source?: 'desk' | 'external'
//   state: 'waiting' | 'overdue' | 'escalated' | 'satisfied' | 'closed'  // 'escalated' is new
//   nudges?: number
//   nudgePending?: boolean
//   lastNudgeAt?: string | null
//   reason?: string | null                                               // 'no_answer_after_reminder'
//   runId: number | null                                                 // null for source 'external'
//   waitingOnName?: string | null

export type DeskHeldReasonV4 =
  | 'needs_review' | 'already_in_progress' | 'already_handled';
// held.target for the last two: { runId: number; messageId: string; stage: string }

export type DeskLifecycleReasonV4 =
  | 'already_scheduled' | 'task_exists' | 'already_in_progress' | 'already_handled'   // with stage COMPLETED
  | 'task_completed'                                                                   // with stage COMPLETED
  | 'task_completion_suggested' | 'task_completion_failed' | 'needs_review';           // with stage ESCALATED

export interface DeskFollowUps {
  account: string;
  followUps: DeskFollowUp[];
  counts: { waiting: number; overdue: number; escalated: number; satisfied: number; closed: number };
  overdueTasks: { id: string; title: string | null; dueAt: string }[];
}

interface Part<T> { ok: boolean; items: T[]; error?: string }
export interface DeskMemory {
  account: string;
  asOf: string;
  scope: { threadId: string | null; sender: string | null };
  meetings: Part<{ id: string; title: string; start: string; end: string; attendees: string[]; organizer: boolean; provider: string }>;
  tasks: Part<{ id: string; title: string; dueAt: string | null; overdue: boolean }>;
  waiting: Part<Pick<DeskFollowUp, 'id' | 'kind' | 'state' | 'waitingOn' | 'subject' | 'threadId' | 'sentAt' | 'dueAt' | 'nudges' | 'nudgePending' | 'runId' | 'source'>>;
  pending: Part<DeskMemoryAction>;
  done: Part<DeskMemoryAction>;
  decisions: Part<{ runId: number; subject: string | null; at: string; decision: string; tool?: string; toolCallId?: number; fields?: string[] }>;
  runs: Part<{ runId: number; kind: DeskRunKind; subject: string | null; from: string | null; threadId: string | null; createdAt: string; stage: string; reason: string | null }>;
}
export interface DeskMemoryAction { runId: number; subject: string | null; tool: string; purpose: string | null; status: string; verified?: boolean; toolCallId: number; start?: string | null; title?: string | null }
```

Client functions to add:

```ts
postCommand(text: string, requestId?: string): Promise<DeskRun>                 // POST /desk/commands
getMemory(params?: { thread?: string; sender?: string }): Promise<DeskMemory>   // GET  /desk/memory
applyTaskUpdate(runId: number, taskId: string): Promise<DeskRun>                // POST /desk/runs/{runId}/task-updates/{taskId}/apply
dismissTaskUpdate(runId: number, taskId: string): Promise<DeskRun>              // POST .../dismiss
```

Timeline: a new evidence kind, `task`. Its `summary` is ready to show.

## 2. Screens

| Where | What to do | Why |
| --- | --- | --- |
| Chat | Send what the person types to `POST /desk/commands` with a `requestId` you generate per send (a retry of the same send then returns the same run). Show `assistantMessage` as the reply, and the run's cards under it as you already show cards. Re-read the run after each approval: the message changes ("is waiting for your approval" becomes "I moved...") | This is the Desk's own instruction path. It is not Scriba's chat agent and needs no model |
| Chat | Do not show `assistantMessage` as if a model wrote it. It is composed by code from the run's state | It can be relied on to match the cards |
| Run detail | A command run has no email: show `command.text` where the message would be, and hide the sender and thread | `email.from_addr` is null |
| Run detail | Show `taskUpdates`. For `state: "suggested"` offer "Mark done" (`applyTaskUpdate`) and "Dismiss". `next` contains `complete_task` exactly then | Finishing a task is the person's to confirm on a real backend |
| Run detail, plan | A deferred step with `state: "waiting"` or `"blocked"` now also appears for `purpose: "notify"` and for a reminder tied to a moved meeting | "Told only after the move went through" is visible there |
| Run detail, cards | Use `action.target.title` for a calendar change. It fixes "No title on the card" on cancel cards | Reported by Agent 4 |
| Work queue | `lifecycle.reason` of `already_scheduled`, `task_exists`, `already_in_progress`, `already_handled` under `COMPLETED`: label as "Already handled" or "Repeat", and link `held.target.runId` when present | A repeat is now done, not "needs you" |
| Work queue | `ESCALATED` with reason `needs_review`: "Could not be placed: read it". With `task_completion_suggested`: "Confirm a finished task" | Two new reasons the person acts on |
| Follow-ups | Show `escalated` as its own state ("Reminded once, still no answer: yours now"). Show `nudges` and `nudgePending`. List `source: "external"` waits; they have no run to open | The Desk never sends a second reminder |
| Follow-ups | Show `overdueTasks` beside the waits | Commitments that are late |
| Overview | `GET /desk/memory` gives "what is on, what is open, what is awaited, what waits for you, what was done" in one call. Where a part has `ok: false`, say "could not be read", never "none" | Unknown is not empty |
| Evaluation | `/desk/eval/v1/meta` now reports `capabilities.chat: true`; conversation cases run. `AgentRun.assistantMessage` is filled for them and a `task.complete` tool call can appear | EVAL-027, 029 and 032 no longer error |

## 3. Behaviour that changed (check your mappings and pinned tests)

1. **`already_scheduled` and `task_exists` are `COMPLETED`**, not `ESCALATED`.
   If a test pins the old stage for a duplicate, it will fail.
2. **Person-written mail the rules cannot place is `ESCALATED` with
   `held.reason: "needs_review"`**, where it was `COMPLETED` with
   `no_action_needed`. Expect more runs under "needs you" on rules alone.
3. `GET /desk/follow-ups` `counts` has a fifth key, `escalated`. A strict
   equality on that object will fail.
4. `/desk/eval/v1/meta` `capabilities.chat` is `true`.

Still true from the last handoff: the three pinned tests in
`frontend/src/live/deskRuns.test.ts`, if you have not yet updated them for
the 0.3 stage names.

## 4. Things I did not do, so you do not look for them

- No route books a NEW meeting from an instruction, and none writes a
  free-form email. "Email Peter that..." is answered with
  `held.reason: "intent_unclear"`.
- `GET /calendar/events` and `GET /tasks` (Scriba's own routes) still do not
  show the sandbox world. `GET /desk/memory` does, for both.
- Follow-up kinds other than `reply` do not exist as records.
- Agent 4's sandbox control routes (`/sim/*`) are not part of the engine.

## 5. How to see it

```
SCRIBA_BACKEND_PATH=<scriba>/Gmail python backend/dev/seeded_desk_server.py --demo --port 8788
# signed in as the seeded user:
POST /desk/commands  {"text": "Remind me tomorrow at 9 to call Peter."}
POST /desk/commands  {"text": "Chase anything I am still waiting on that is overdue."}
GET  /desk/memory
```

The demo world has its own meetings; an instruction to move one must use
words from that meeting's title.
