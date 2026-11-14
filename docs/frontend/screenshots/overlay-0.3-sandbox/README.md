# Screenshots: live mode on Desk overlay 0.3, in the sandbox

Taken on 14 November 2026 by a scripted Chrome session, signed in as a seeded test user, against
`agent1/autonomous-engine` at `e86f449` started with `python backend/dev/seeded_desk_server.py
--demo`. That backend gives the user an isolated sandbox world: stand-ins for Gmail, Outlook and
both calendars, with fictional people on reserved `.example` addresses. No real mailbox or calendar
was involved, nothing real was sent, and nothing here is a result about the agent.

Nothing was intercepted or staged. Before these were taken, three proposals were approved through
the screens, in the sandbox: a booking, a reply offering times, and a task.

| File | Screen |
| --- | --- |
| `work.png`, `work-phone.png` | Work queue: the worker's status, runs by list, the stage and progress of each run |
| `run-awaiting-reply.png`, `run-awaiting-reply-phone.png` | Run detail after an approved reply ran: stage "Awaiting reply", the rail with recorded times |
| `run-next-step.png` | Run detail after a booking ran and the confirmation was proposed |
| `run-escalated.png` | Run detail for a message with text addressed to the assistant: escalated, nothing proposed |
| `overview.png`, `overview-phone.png` | Overview: waiting on you, with the secretary, runs by list, finished work |
| `follow-ups.png`, `follow-ups-phone.png` | Follow-up workspace: one reply awaited |
| `approvals.png` | Approval center in sandbox mode, with the readiness checks for real sending |
| `evaluation.png` | Evaluation: the three kinds of result |
| `run-plan.png`, `run-plan-phone.png` | The plan of a run after both of its steps were approved in the sandbox: cancel the meeting, then tell the sender. Taken against `0282558` |
| `run-plan-blocked.png` | The plan of a run whose first step was rejected: the step that depends on it is blocked and is never proposed. Taken against `0282558` |

Desktop images are 1440 by 900, phone images 375 by 844.

Not shown, because this session's sandbox did not produce them: a partly completed run, a failed
execution, an unknown outcome, an overdue or answered follow-up. Those are covered by tests.
