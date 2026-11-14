# Screenshots: the "midnight and iris" theme

Taken on 14 November 2026 by a scripted Chrome session, signed in as a seeded test user, against
`agent1/autonomous-engine` at `0282558` started with `python backend/dev/seeded_desk_server.py
--demo`: an isolated sandbox world with fictional people on reserved `.example` addresses. No real
mailbox or calendar was involved and nothing here is a result about the agent.

These replace the look of the earlier sets, not their content: the other folders under
`docs/frontend/screenshots/` still show the previous dark burgundy colours. Only colours, shadows
and the favicon changed; no screen, wording or behaviour did.

| File | Screen |
| --- | --- |
| `overview.png`, `overview-phone.png` | Overview |
| `work.png` | Work queue |
| `run.png`, `run-phone.png` | A completed run with its plan |
| `approvals.png`, `approvals-phone.png` | Approval center in sandbox mode |
| `inbox.png`, `inbox-phone.png` | Inbox |
| `chat.png`, `calendar.png`, `tasks.png`, `activity.png`, `evaluation.png` | The other screens |

Desktop images are 1440 by 900, phone images 375 by 844. All ten screens were also loaded at 768 px:
no horizontal overflow, no failed request and no console error at any of the three widths.

Colours are tokens in `frontend/src/index.css` (and the brand scale in `frontend/tailwind.config.js`).
Every text colour is above 4.5:1 on each of the three surface levels; the lowest is muted text on a
raised surface at 5.5:1, and white on the primary button is 5.5:1.
