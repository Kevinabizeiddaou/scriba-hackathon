# Jira in the Desk (skeleton, 0.1.0)

Off by default. With `DESK_JIRA` unset the Desk is the four-capability product it was:
no Jira route answers except `GET /desk/jira/status` (`enabled: false`), no screen shows
it, and no existing payload names it. Setup is in [SETUP.md](SETUP.md).

## What it is

- **Backend**: `backend/desk_overlay/jira/`, mounted under `/desk/jira/` by `install.py`.
- **Frontend**: `frontend/src/live/jira/` and `frontend/src/api/jira.ts`; the **Jira** entry in
  the navigation appears when `/desk/health` reports `jira.enabled`.
- **Sign-in, token storage and refresh are Scriba's**, reached through three methods on
  `ScribaGateway` (`jira_connection`, `jira_token`, `jira_send`). The Desk stores no token.

## The rule

Nothing changes Jira from a button press. A change is one of 18 catalogued **actions**
(`actions.py`), and it goes through:

1. **propose**: the input is validated, what only Jira knows is read and pinned (a
   transition's id, the issue's current status, a person's name), and a one-sentence
   preview is recorded. Nothing is written.
2. **approve**: a person's decision. Two approvals run it once. With Jira writes off it is
   **held** and nothing is sent. If the issue moved on since the proposal it is not applied.
3. **read-back**: the result is read from Jira. A change Jira accepted that does not read
   back as approved is shown as "Done, not confirmed", never as a success. A request that
   died on the way is "outcome unknown" and is not retried until the person says they looked.

There is no action that deletes an issue, and none that changes many issues at once.

| Where it runs | What approving does |
| --- | --- |
| A sandbox world (`DESK_DEMO`, evaluation) | Applied to a synthetic Jira site. Labelled Simulated. The real connection is never touched |
| Live, `DESK_JIRA_WRITES` unset (default) | Held: `jira_writes_disabled`. Nothing is sent |
| Live, `DESK_JIRA_WRITES=on` and `DESK_JIRA_WRITES_AUTHORIZED_BY` set | Sent to the person's Jira site, then read back. Recorded in Scriba's audit log |

## Routes

All need a Scriba session. A Jira-side authentication problem is a **409** with
`errorCode` `not_configured`, `not_connected` or `reconnect_required`, never a 401: to the
Desk's client a 401 means the Scriba session is gone.

| Route | What it returns |
| --- | --- |
| `GET /desk/jira/status` | State, site, granted scopes, write mode, and what is missing to set up (names only) |
| `GET /desk/jira/features` | The coverage map below, per connection, and the action catalogue |
| `GET /desk/jira/briefing` | Late, blocked, due, stalled, unowned; running sprints' health; approvals waiting |
| `GET /desk/jira/issues` | A named `view`, filters, or `jql`. Token paging. `count=true` adds an approximate count |
| `GET /desk/jira/issues/{key}` (+ `/comments`, `/history`) | One issue with text, comments, links, sub-tasks, available moves |
| `GET /desk/jira/people` | Who can be assigned or mentioned |
| `GET /desk/jira/projects` (+ `/{key}`, `/{key}/create-fields`, `/{key}/releases`) | Projects, issue types, the create form's fields, release progress |
| `GET /desk/jira/filters` (+ `/{id}/issues`), `/dashboards` | Saved filters and their issues; dashboard names |
| `GET /desk/jira/boards` (+ `/{id}`, `/{id}/backlog`), `/sprints/{id}` | Boards, columns, backlog, a sprint with its health and workload |
| `GET /desk/jira/approvals` | Service requests waiting on the person |
| `POST /desk/jira/proposals`, `GET`, `POST /{id}/approve`, `POST /{id}/reject` | The only way anything changes |

## Coverage

59 features are catalogued in `features.py` and served at `/desk/jira/features`; the
Coverage tab shows them. 37 are ready (route and screen or action), 4 are served without a
screen, 13 are planned with the Jira endpoint they need, 5 are left out with the reason.

| Area | Ready | Planned or left out |
| --- | --- | --- |
| Connection | Sign-in, status, disconnect (Scriba's) | Choosing between several sites; API tokens (left out) |
| My work | Assigned, due, overdue, reported, watching, mentions, briefing | Recently viewed and starred; the notification bell (no API) |
| Projects | Project list and detail (issue types, components); need `read:project:jira` | |
| Search | Filters, JQL, saved filters | Saving a filter; dashboard contents (Jira returns settings, not data) |
| Issue | Read, comments, history, hierarchy and links; create, edit, move, assign, comment, log time, link, watch | Edit or delete a comment, attach a file, flag, vote, bulk change; delete (left out) |
| Boards and sprints | Boards, columns, backlog, sprints, sprint health; move, rank, create, start, complete | Burndown, velocity, cumulative flow (no API: computed from history) |
| Releases | Versions with progress; create and release | |
| Service management | Approvals waiting on me; approve or decline | Queues and SLA |
| Staying current | | Webhooks; Jira issues as incoming work for the secretary; Jira in the secretary chat |
| Outside the API | | Automation rules and plans (left out: not open to OAuth apps) |

What "most used" rests on: Jira's own home page (assigned to me, due soon, mentions,
approvals waiting), its board and issue views, and what Atlassian recommends leaders put on
a dashboard (sprint health, blocked and flagged work, workload). Atlassian publishes no
ranked usage data, so the order is a judgement.

## Decisions taken from Atlassian's current API

- Search is `POST /rest/api/3/search/jql` only (the old `/search` answers 410). It pages by
  token, has no total, defaults to returning ids only, and refuses a query that restricts
  nothing: every view is bounded and every search names its fields.
- The issues of a board, backlog and sprint are read from `/rest/software/1.0`. The
  `/rest/agile/1.0` forms are deprecated; they are tried only when the new path is not found.
- `GET /priority` and `GET /resolution` are deprecated and unused: allowed values come from
  the create, edit and transition metadata.
- People are named by `accountId` only. A mention is written `[~accountid:<id>]`.
- Rich text is ADF. `adf.py` builds it and never emits an empty text node, which Jira refuses.

## Not verified yet

Everything above ran against the synthetic site, through the real client, on the real
Scriba app in Docker. Nothing has run against a real Jira site: there are no credentials
yet. To check on the first real connection:

- The JQL of two views is common practice but not in Atlassian's reference: **Mentioning
  me** (`text ~ currentUser()`) and **Blocked or flagged** (`flagged is not EMPTY`). A site
  that refuses one shows the error on that view only.
- Whether the deprecated Agile listings are already removed (the fallback covers both cases).
- What completing a sprint through the API does with unfinished issues.
- `backend/tests/integration` has no Jira test: the overlay's Jira code is covered by
  `backend/tests/test_jira.py` (61 tests, no Scriba needed) and the frontend by
  `frontend/src/live/jira/JiraPage.test.tsx`.

## Known limits of the skeleton

- **Proposals are kept in memory.** A restart forgets the ones not yet decided (the status
  says `durable: false`). Decisions and writes on a real site also go to Scriba's audit log.
  The durable store is the next step: Scriba's action cards, which would also put Jira
  changes in the Approval center.
- **The secretary chat still excludes Jira** (`chat_scope.py` is unchanged). Scriba has four
  Jira chat tools; they are left out until a card for them is governed by this gate, because
  the Desk's execution gate holds mail and calendar tools only.
- The workspace has no screens yet for edit-issue fields, sprint planning, releases and
  service approvals: their actions and routes exist and are tested.
