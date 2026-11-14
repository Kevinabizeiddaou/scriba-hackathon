# Screenshots: live mode on the seeded backend

Taken on 14 November 2026 by a scripted Chrome session, signed in as a seeded user, against
Scriba's seeded test backend with the Desk overlay (`backend/dev/seeded_desk_server.py`, Scriba at
`3ae3a2a`). That backend is the real application with in-memory storage: no database, no provider
network, no model. Its people and messages are Scriba's own test fixtures.

Nothing was intercepted or staged. Each image shows what that backend answered. No real mailbox or
calendar was involved, and nothing here is a result about the agent.

| File | Screen | What the backend had |
| --- | --- | --- |
| `overview.png` | Overview | Seeded mail, tasks and one action card waiting in chat |
| `work-queue.png`, `work-queue-phone.png` | Work queue, after "Check for new work" | 25 messages examined, none needing work; one earlier run with no action |
| `run-detail.png`, `run-detail-phone.png` | Run detail | A run for an informational message: picked up, classified, no action needed |
| `find-a-time.png`, `find-a-time-phone.png` | Scheduling workspace | No calendar connected, so no time is offered and availability is stated as unknown |
| `approval-center.png` | Approval center | The seeded task proposal; sending and calendar changes are switched off |

Desktop images are 1440 by 900, phone images 390 by 844.

Not shown, because the seeded backend cannot produce them: a run waiting for approval, a held
meeting request, an executing or partly executed run, a verified result, free slots, a calendar
conflict. Those states are covered by tests on the contract's shapes.
