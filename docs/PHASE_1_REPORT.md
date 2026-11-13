# Phase 1 report

Checkpoint: index card, due Saturday 14 November 2026, 10:00.
Recorded 2026-11-13.

## Repository

- https://github.com/Kevinabizeiddaou/scriba-hackathon, branch `main`
- Stage 1 code: commit `f8b933b`
- Phase 1 submission documents: the commits after it on `main`; the latest
  one is the official submission

## Submission

The index card is [INDEX_CARD.md](INDEX_CARD.md): whose weekly job, the
trigger, the workflow steps, and what successful completion means. This is
the canonical first submission.

An alternative draft card is kept for reference on the
`role2/frontend-evaluation` branch at
`executive-desk/docs/submission/INDEX_CARD.md`.

## Files transferred from Scriba

From `ScribaAssist/Scriba`, `Gmail/frontend` at `3ae3a2aa`. Each file carries
a header naming its source.

| File here | Source | Change |
| --- | --- | --- |
| `frontend/src/lib/apiBase.ts` | `src/lib/apiBase.ts` | None |
| `frontend/src/api/client.ts` | `src/api/client.ts` | A lost session returns to the sign-in screen instead of starting a provider sign-in |
| `frontend/src/hooks/useProviderStatus.ts` | `src/hooks/useProviderStatus.ts` | Import paths; Desk cache key |
| `frontend/src/index.css` | `src/index.css` | Landing-page and excluded-integration styles left out |
| `frontend/tailwind.config.js`, `postcss.config.js`, `tsconfig.json`, `src/test/setup.ts` | Same names | None |

Written for the Desk: the typed API subset (`src/api/contract.ts`,
`src/api/scriba.ts`), the four-capability connection model
(`src/lib/connections.ts`), the shell (`src/shell/`, `src/App.tsx`), the
smoke test and the secret check (`scripts/`).

No backend code was transferred. The Desk calls Scriba's existing API.

## Tests and build

| Check | Result |
| --- | --- |
| Unit tests | 11 of 11 pass |
| Typecheck and production build | Pass |
| API smoke on Scriba's seeded test backend (anonymous + signed-in) | 18 of 18 pass |
| API smoke on the existing hosted Scriba API (anonymous, read-only) | 9 of 9 pass |
| Shell in a browser on the seeded backend | Sign-in, connection cards and Gmail list work |
| Secret scan and ignore rules | Clean |

## Baseline

Zero end-to-end secretary runs, and zero of 20 evaluation cases executed
(so no pass rate exists; this is not a 0% result). Live Google
and Microsoft data have not been tested from the Desk. Details and the list
of what is unverified are in [BASELINE.md](BASELINE.md).

## Outstanding blockers

- Live verification needs a real signed-in session with connected Google and
  Microsoft accounts; none was used in Phase 1.
- Hosting the Desk anywhere other than `localhost:5173` needs the
  configuration decisions in [ARCHITECTURE.md](ARCHITECTURE.md).
- Backend issues found in Scriba are tracked privately in Scriba's
  repository; none is fixed yet.
- The frontend and evaluation work is on the `role2/frontend-evaluation`
  branch, which has an unrelated history. It is preserved as is and has not
  been merged into `main`. It runs on a scripted mock, not on Scriba's API.

## Expanded scope

After the first version of this report the product was redefined, from
meeting scheduling to the whole job of turning an executive's incoming
correspondence into verified administrative outcomes. This changed the
documents only: the index card, the README and the new
[ROADMAP.md](ROADMAP.md) with the feature reuse matrix and the feature-by-
phase plan. No code changed, and the test results above are the same runs.

The index card keeps a placeholder for the real job-holder, to be supplied
by the project lead.

## What Phase 2 will include

Not started, and not to be started without authorization. Phase 2 is
read-only: nothing is sent and no calendar is changed.

- A live signed-in read on Gmail, Outlook Mail, Google Calendar and Outlook
  Calendar, to replace seeded data as the evidence.
- One inbox across Gmail and Outlook, with threads.
- Priority and triage, search, and reply drafts for review.
- Chat on Scriba's existing agent.
- Day and week calendar views across both calendars.
- Notifications and an on-demand daily briefing.

Scheduling, tasks, reminders, automations, approvals and all outbound
actions are Phase 3. The 20 real cases, metrics and demo are the final
phase. See [ROADMAP.md](ROADMAP.md).
