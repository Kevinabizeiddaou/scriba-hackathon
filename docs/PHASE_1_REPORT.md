# Phase 1 report

Checkpoint: index card, due Saturday 14 November 2026, 10:00.
Recorded 2026-11-13.

## Repository

- https://github.com/Kevinabizeiddaou/scriba-hackathon, branch `main`
- Stage 1 code: commit `f8b933b`
- Phase 1 submission documents: the commit that adds this file

## Submission

The index card is [INDEX_CARD.md](INDEX_CARD.md): whose weekly job, the
trigger, the workflow steps, and what successful completion means.

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

Zero end-to-end secretary runs and zero of 20 evaluation cases. Live Google
and Microsoft data have not been tested from the Desk. Details and the list
of what is unverified are in [BASELINE.md](BASELINE.md).

## Outstanding blockers

- Live verification needs a real signed-in session with connected Google and
  Microsoft accounts; none was used in Phase 1.
- Hosting the Desk anywhere other than `localhost:5173` needs the
  configuration decisions in [ARCHITECTURE.md](ARCHITECTURE.md).
- Backend issues found in Scriba are tracked privately in Scriba's
  repository; none is fixed yet.
- The frontend and evaluation role has not yet started on its branch.

## What Phase 2 will include

Not started, and not to be started without authorization.

- Fixes to existing Scriba backend issues, as small separately reviewable
  pull requests in Scriba's repository, each with a regression test. No merge
  or deploy without authorization.
- A read-only availability service under `/desk/*`: real Google and Outlook
  calendar availability for the signed-in user, combined busy intervals,
  timezone, working hours, duration and buffers, conflicts across both
  providers, suggested free slots, provider and account identity preserved,
  no calendar writes.
- The overlay source versioned in this repository with reproducible
  integration instructions, and a typed contract for the frontend role.
- Validation across Google-only, Microsoft-only, both, none, conflicts,
  expired permissions, time zones, cross-user isolation, API failures and
  fully booked calendars.
