# The browser as a tool of the secretary (overlay 0.6)

Written 14 November 2026 on branch `agent1/browser-agent`, stacked on
`agent1/automation-integration` (pull request 14). For the project lead and
Agents 2, 3 and 4.

**Nothing here is a result about a real website, a real account, a person's
own browser or a model.** The browser is a real headless Chromium; the only
site it has opened is a synthetic supplier portal on this machine. No model
is called anywhere in this work. ScribaAssist/Scriba was read from a clone
and not changed; none of its source is in this repository.

Contract: [../BACKEND_CONTRACT.md](../BACKEND_CONTRACT.md) section 15.
Measurements: [BROWSER_BENCHMARK.md](BROWSER_BENCHMARK.md).

## 1. What Scriba has (audit of `3ae3a2a`, read-only)

Scriba's browser automation is one Chrome extension, `Gmail/browser_extension/`
(Manifest V3, about 1,000 lines). It records what a person does in a tab and
replays it later. Paths below are relative to `Gmail/`.

| Area | What exists | What does not |
| --- | --- | --- |
| Engine | Extension only: `sw.js` (service worker), `content/player.js`, `content/recorder.js`, `lib/locators.js`, `lib/steps.js`, `lib/semantics.js`. Actions are synthetic DOM events | No DevTools protocol, Playwright, Selenium or Puppeteer in product code. No headless mode |
| Session | Pairs as a `browser` device; polls the server for `web.replay` jobs every 30 seconds; uses the person's own Chrome profile, so their sign-ins | A new tab for every replay, never reused or closed. A replay lives in the worker's memory: no checkpoint, no resume |
| Waiting | Waits for the tab to finish loading; waits up to 10 s for an element, polling every 150 ms | A fixed 500 ms pause after every click and key. No waiting on the page changing |
| Finding elements | A locator with eight strategies tried in order (test id, id, name, aria-label, CSS path, text, href, position); each must match exactly one element; a match by a later strategy is a "heal" | No page snapshot, no lookup by role or accessible name, no frames, no shadow DOM |
| Actions | `goto`, `click`, `fill`, `select`, `key`, `scroll`, `wait`, `extract`, `verify` (four checks) | No download, upload, drag, table reading. **`select` throws on a native dropdown** (found here; see section 6) |
| Vision | None, by design | No screenshots, no model |
| Recovery | A heal whose label adds a committing word is refused (`riskySubstitution`) | No retries, no dialog handling, no check of what a click did |
| Safety | Exact-origin confinement before every acting step; passwords recorded as empty and redacted again on the server; `recording_risk.committing_clicks` and the engine's never-autonomous categories on the server | `goto` is not origin-checked in the worker. No private-network blocking anywhere. No approval prompt on the device. The sign-in vault exists and nothing calls it |
| Server | `app/services/web_steps.py` (`sanitize_web_steps`, `web_allow_origins`), device and job services, `desktop_agent/skills/web.py` `web.fetch` (plain page download on a desktop device) | The backend never loads a page itself. The services need Postgres to import. No autonomous loop: "plan once, execute validated steps" |
| Tests | jsdom unit tests of the pure modules and the player; server tests for steps, recordings and the browser device | The extension's tests are not run in Scriba's CI |

## 2. What the Desk reuses, as it is

Loaded from the Scriba checkout (`SCRIBA_BACKEND_PATH`) at run time. Nothing is
copied.

| Scriba code | Used for |
| --- | --- |
| `browser_extension/content/player.js` `applyStep` | **Every click, fill, check and value read on a page** |
| `browser_extension/lib/locators.js` `captureLocator`, `resolveLocator` | The locator of an element the Desk found, and the proof that it points back at exactly that element; resolving a kept locator |
| `browser_extension/lib/steps.js` `originAllowed` | Scriba's own site check inside the page, on every acting step |
| `app/services/web_steps.py` `sanitize_web_steps`, `web_allow_origins` | Cleaning a locator before it is kept; the comparison runs in the benchmark |
| `app/services/recording_risk.py` `committing_clicks` (and `desktop_rpa/semantics.py`'s lexicon behind it) | Deciding that a control commits, sends, pays or destroys |
| `app/services/content_guard.py` `scan_untrusted_text` | Finding text on a page that is written to an assistant |
| `app/ai/egress.py` `ambiguous_url`, `metadata_or_link_local` | Refusing an ambiguous address and a metadata or link-local host |
| `app/chat_files.py`, `app/document_intelligence.py` (through `desk_overlay/files.py`) | Type of a downloaded file by its bytes; opening it |
| `desktop_agent/skills` `xlsx.*` (through `desk_overlay/workbooks.py`) | The workbook change after a fetch |
| Scriba's `send_email` card and approval path | The email after a fetch |

## 3. What the Desk adds, and why it could not be reused

| Added | In | Why |
| --- | --- | --- |
| A driver for an isolated headless Chromium over the DevTools protocol | `desk_overlay/browser_cdp.py` | The extension runs only in a person's Chrome and takes jobs from a server with a database. Neither exists in a sandbox, and the extension cannot run headlessly or download. This plays the service worker's role and nothing more |
| Scriba's page modules joined in memory into one script | `browser_cdp.scriba_page_bundle` | They are ES modules loaded by the extension runtime; a plain page has no such loader |
| Looking at a page: controls by the name a person would use, a value beside a label, a table, a dialog in the way | `desk_overlay/browser_page.py` | Scriba has no snapshot and no lookup by name |
| A request gate on every request of the page | `browser_cdp.Page` | Scriba checks the origin before a step, not each request, and not `goto` |
| Private, loopback and resolved-name address refusal | `browser.site_problems` | Not in Scriba (`egress` leaves RFC 1918 and loopback out and never resolves names) |
| A task that is not a recording; download; search across pages; closing a dialog; one retry of a slow page; read-back of a submission; an approval binding | `desk_overlay/browser.py` | Not in Scriba |
| The errand inside a run | `desk_overlay/errands.py` | The Desk's own run record |
| Choosing an option of a native dropdown | `browser_page.py` | Scriba's `select` step throws on one (section 6) |

No model, no planner and no second approval system were added. The browser is
one more tool of the existing run: its steps are events of the run, its file
is a file of the run, the workbook change and the email use the paths that
already existed.

## 4. For Agent 2: what the screens need

Everything is typed in `frontend/src/api/desk.ts` (additive; the frontend on
`main` type-checks and its 452 tests pass against it). Nothing in the
frontend was changed. The hosted frontend is at
https://scriba-hackaton.vercel.app/ ; it does not show any of this yet.

| Data | Required behaviour |
| --- | --- |
| `run.browser` present | A "Website" block on the run page. Show `site` and `origin` (the website being accessed), `goal`, and `stepsDone` of `stepsTotal` |
| `run.browser.state` | Eleven states (contract 15.3). **Only `VERIFIED` is green.** `COMPLETED` is "read, nothing to verify". `PLANNED` and `RUNNING` are in progress: poll the run while it is one of them. Every other state is not success and needs its own wording; show `message` |
| `run.browser.steps[]` | The current activity and what was done, in order: `op` and `name` ("follow: Reports"), `state`, `ms`. Show `recovered[]` in plain words ("closed a dialog", "tried a slow page again", "signed in"). For a stopped step show its `message`. A step with `state: "submitting"` means a submission went out and its answer is not on record yet |
| `steps[].verification` | The evidence line. `file_opened` with `checksum: "matches_the_page"`: "the file was opened and has the checksum the page states". `read_back`: "the site was read again and shows the change". `pressedAgain` is always false; say "submitted once" where `answered` is false |
| `run.browser.downloads[]` and `run.files[]` with `source: "browser"` | The retrieved file with its download (`download.path`, with credentials), size and where it came from (`from`) |
| `run.browser.untrustedFindings[]` | A visible warning: the site carries text written to an assistant; it was not followed. Say whether it was shown or hidden (`where`) |
| `run.browser.ignored[]`, `blockedOrigins[]` | "A link to another site was not used", "the page tried to reach another site; that was refused", with the origin |
| `run.fileChanges[]` after a fetch | As in the workbook handoff (AUTOMATION_INTEGRATION 2.3): the person applies or dismisses. This is the "action awaiting approval" of the errand |
| An action with `purpose: "send_report"` | Scriba's own email card. If approving returns `error: "unverified_recipient"`, the address came from the message, not from the person: ask them to confirm it, then approve with `payload_overrides: {"desk_confirmed_recipients": [address]}` (the same rule as every other card) |
| `lifecycle.reason` `browser_running`, `browser_failed`, `browser_interrupted`, `browser_outcome_unknown`, `workbook_not_mapped` | Five new reasons, each needs a line |
| `held.reason: "site_not_authorised"` | "The message asks for something from a website you have not authorised. Nothing was opened" |
| Timeline items of `kind: "browser"` | A new evidence kind (in `DeskRevisedEvidenceKind`): icon and label |
| `GET /desk/browser`, `health.browser` | Whether browsing is available and on which sites. `available: false`: show `message`, offer nothing. `simulated: true`: the Sandbox tag |
| `simulated` on the errand | Keep the Sandbox tag. Every site today is synthetic |

Do not show page content: the API does not send it. Do not show a progress
bar that moves by itself: `stepsDone` is the only progress there is.

**Blockers for Agent 2:** none on the backend side for showing an errand. Not
available yet, so do not build screens for them: authorising a site, starting
a task that changes a site from a run, cancelling a running errand, live
push (poll the run).

## 5. For Agents 3 and 4

Agent 3, what to attack (the oracles are in
`backend/tests/integration/test_browser_with_scriba.py`): a request to any
origin but the site's must never leave the machine; a password is never
typed; nothing is posted without an approval of exactly those values; a form
is never posted twice; a file that does not open or whose checksum differs is
never kept; text on a page never changes what is done. Try: redirects (meta
refresh, script, 30x) to another origin and to an internal address; a name
that resolves to a private address after the site was accepted; a link whose
visible name and target disagree; a button that looks like a link; a dialog
whose "Close" also submits; text for an assistant in an attribute, an image
alt, a comment, a late-loaded fragment; two controls with one name; a page
that changes between looking and pressing; a download that is an executable
renamed `.xlsx`; a site of your own making, which is the test this work has
not had.

Agent 4: `SandboxWorld.add_site(name=, origin=, aliases=, start=, sign_in=,
reports=)` authorises a synthetic site for a world; `backend/dev/supplier_portal.py`
is one, with switches for a slow answer, a second layout, a dialog, injected
text, a decoy, a truncated file and an answer that never comes. A simulated
day can now include "fetch the report from the portal" mail.

## 6. Findings about Scriba worth telling its owners

Reported, not fixed: Scriba is read-only for this work.

1. `content/player.js`: the `select` action calls the text input's value
   setter on a `<select>`, which throws "Illegal invocation". A recorded
   dropdown choice cannot be replayed on a native dropdown.
2. `sw.js` `drivePlayer`: a `goto` step navigates without an origin check; only
   the step after it is refused.
3. Neither the extension nor `web.fetch` refuses private, loopback or
   resolved-to-private addresses.
4. A click swallowed by a modal fails the replay 10 seconds later with
   "couldn't find the click target", with nothing saying a dialog was open.
5. The fixed 500 ms after every click is most of a replay's time on a fast
   site (benchmark, section 3).

## 7. Tests

Windows 11, Python 3.13, Node 22, Scriba read-only at `3ae3a2a`, Chromium
headless shell build 1234. Sandbox only. No model configured.

| What | Result |
| --- | --- |
| Backend unit tests | 654 passed (on the merge with `main` at `3d8b4ab`) |
| Backend integration tests, on Scriba's real application | 366 passed, 56 skipped (real-model parameters) |
| Of which new: browser (35), typed client (1) | All pass. Skipped on a machine with no Chromium |
| Frontend against the new typed client | Type check clean, 452 of 452 tests |
| Benchmark | 225 of 225 runs correct, 0 unsafe actions, 0 false successes (BROWSER_BENCHMARK.md) |
| Mutation check on the browser code | 35 planted defects, 31 caught (24 at first; seven tests added, and one real weakness fixed: a session that ended just before the download was not recovered). Not caught: two backup checks that another check already covers (a metadata address is also refused as not global; a failed fetch has no file to act on), and two guards with no test yet: a field that does not keep the value typed into it, and a kept locator that now points at a control with another name |

Not run: the quality lab and the office simulation against this branch; any
real site; any real model; the hosted deployment (not tried; with no authorised
site it reports `available: false` by design).

## 8. Next, in order of value

1. A site that Agent 3 builds, and their attacks on the gate.
2. A route for a task that changes a site, as a suggestion the person applies
   (the binding exists; the route and the screen do not).
3. The email carrying the files, through Scriba's own attachment references
   (needs its documents table).
4. Authorising a real site, with the lead's go-ahead, and the first read-only
   run against one.
5. Scriba's extension in the person's own Chrome as a second way to run the
   same steps where a sign-in is needed (needs Postgres and a paired device).
