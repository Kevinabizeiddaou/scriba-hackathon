# Evaluation baseline

Recorded 2026-11-13, at the end of Phase 1.

## Headline

**End-to-end secretary runs completed: 0.** The agent workflow on the index
card has not been run, in whole or in part, from this repository. No email
has been sent and no calendar event has been created, changed or cancelled.

**Scheduling evaluation: 0 of 20 cases executed.**

| Measure | Value |
| --- | --- |
| Cases defined | 20 |
| Cases executed against a real backend | 0 |
| Cases passed | Not measured |
| Cases failed | Not measured |
| Pass rate | Not measured |

This is "nothing has been run", not "everything failed" and not "0% passed".
There is no pass rate until cases are executed against a real backend.

The 20 cases and the evaluation harness are on the
`role2/frontend-evaluation` branch. That harness has only been pointed at
its own scripted mock, which checks the harness, not the agent. Results from
the mock are not agent results and are not counted here.

## What Phase 1 does demonstrate

| Check | Result | Against |
| --- | --- | --- |
| Unit tests (`npm test`) | 11 of 11 pass | — |
| Typecheck and production build (`npm run build`) | Pass | — |
| API smoke, anonymous and signed-in (`scripts/smoke.mjs`) | 18 of 18 pass | Scriba's seeded test backend, running locally: real Scriba application code, in-memory data, no provider network |
| API smoke, anonymous checks only | 9 of 9 pass | The existing hosted Scriba API (read-only requests, no sign-in) |
| Shell in a browser: sign-in, four connection cards, Gmail list | Works | Seeded test backend |
| Secret scan (`scripts/check-no-secrets.mjs`) | Clean | Files tracked by Git |

The signed-in smoke covers: session cookie issued on sign-in; connection
status for Gmail, Google Calendar, Outlook Mail and Outlook Calendar; a mail
page per provider; a calendar range per provider; refusal of another user's
account; refusal of a state-changing request from an untrusted origin;
sign-out.

## What has not been verified

| Area | Status |
| --- | --- |
| Live Gmail data | Not tested. The mail shown came from seeded test data. |
| Live Outlook Mail data | Not tested. The route answered with an empty page for a user with no Outlook account. |
| Live Google Calendar data | Not tested. The route answered with an empty range. |
| Live Outlook Calendar data | Not tested. The route answered with an empty range. |
| Signed-in use of the hosted Scriba API from the Desk | Not tested. It needs a real user session. |
| Google or Microsoft sign-in started from the Desk | Not tested end to end. The shell links to Scriba's sign-in routes. |
| Reading a thread, extracting a request, checking availability, proposing slots | Not built. |
| Approval, calendar write, threaded reply, follow-up, execution log | Not exercised from the Desk. |
| Cost per run | No runs, so no cost. |

## How to reproduce

```bash
cd frontend && npm install && npm test && npm run build
node scripts/smoke.mjs --base <scriba api>                      # anonymous
SMOKE_EMAIL=... SMOKE_PASSWORD=... node scripts/smoke.mjs --base <local scriba api>
node scripts/check-no-secrets.mjs
```
