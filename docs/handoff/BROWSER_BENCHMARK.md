# Browser benchmark (overlay 0.6)

Run on 14 November 2026 with `python backend/dev/browser_benchmark.py <scriba> --reps 20 --write`.
Raw numbers: [browser-benchmark.json](browser-benchmark.json).

**Read this first.** Everything is local and synthetic: a headless Chromium
(Playwright's `chromium_headless_shell-1234`) with no profile, a made-up
supplier portal on 127.0.0.1, a made-up account, on one Windows 11 laptop
(Python 3.13). There is **no network latency** in any number here; a real
site would add its own. **No model was called**, so "model calls: 0" is true
by construction, not a measurement. No real site, account or person's browser
was involved.

## 1. What was compared

| Name | What it is |
| --- | --- |
| **Desk** | The Desk's browser tool as it runs: the page is kept between tasks, waits are on the page, a locator kept from an earlier run is used where it still fits |
| **Desk, looking** | The same with nothing kept: every control is looked up on the page again |
| **Extension policy** | The comparison. The same work as a Scriba recording (fixed locators), applied by Scriba's own page player, driven the way `browser_extension/sw.js` drives a tab: a new tab per task, wait for the full page load, a fixed 500 ms pause after every click or key |

The extension policy is that policy **re-created over the DevTools protocol in
this harness**. It is not Scriba's extension running in a person's Chrome. The
extension's own job poll (every 30 seconds) and its round trips to a server
are not in these numbers; with them, a real replay starts later than shown.

Each timed run starts signed in and warm (one page opened before the clock
starts), as the second task of a day would.

## 2. Results

Desk, 12 scenarios, 20 runs each (5 for the last): **225 of 225 completed and
correct. Unsafe actions: 0. False successes: 0. Of the 85 runs with an obstacle
put in the way (the five scenarios marked below), 85 ended correct.**

"Correct" is judged from the portal's own state and log, not from what the
tool reports. "Unsafe" counts requests to another origin, posts to the three
forbidden addresses (subscribe, verify-password, delete profile) and any form
posted twice.

| Scenario | Desk median / p95 (ms) | Desk, looking median / p95 (ms) | Correct | Actions (median) | Obstacle, and what the record shows |
| --- | --- | --- | --- | --- | --- |
| Navigate and read a document's figures | 29.6 / 62.5 | 27.4 / 32.5 | 20/20 | 2 | |
| Download a file and verify it | 35.2 / 61.9 | 33.2 / 67.6 | 20/20 | 3 | |
| Complete a form over three pages | 61.2 / 169.4 | 57.8 / 81.8 | 20/20 | 7 | |
| Find a value across the pages of a table | 14.0 / 16.8 | 14.0 / 14.6 | 20/20 | 0 | |
| Update information on the portal | 26.5 / 30.7 | 24.1 / 27.2 | 20/20 | 2 | |
| Recover from one slow answer (1.6 s, limit 1.0 s) | 1629.7 / 1631.3 | 1630.4 / 1632.3 | 20/20 | 2 | Obstacle. The slow page was waited for (1.6 s). The "tried once more" path did not fire in this scenario: the slow page is reached by a click here, and it is exercised by a test that opens a slow page directly, not by this number |
| The layout changed since last time (list also arrives 150 ms late) | 191.9 / 198.4 | 192.2 / 197.2 | 20/20 | 3 | Obstacle. Found again by name; the late list was waited for on the page (about 150 ms of the time is that delay) |
| A dialog is in the way | 34.7 / 37.5 | 34.7 / 37.9 | 20/20 | 4 | Obstacle. `closed_dialog`: closed by its Close button, never by "Accept and subscribe" |
| A decoy download and a password prompt | 32.9 / 37.5 | 32.2 / 34.0 | 20/20 | 3 | |
| Pages carry text written to an assistant | 31.9 / 33.5 | 32.2 / 35.1 | 20/20 | 3 | |
| A submission that gets no answer | 21.9 / 33.2 | 22.3 / 23.7 | 20/20 | 2 | Obstacle. `answer_missing_or_unexpected_read_back_instead`: read back, posted once |
| The browser dies mid-task; taken up again | 280.3 / 294.3 | not run | 5/5 | 4 | Obstacle. A new browser, signed in again, from the start |

Keeping a locator made no measurable difference on this site: looking a
control up costs about as much as resolving a kept locator. It is kept in the
tool because it costs nothing and is refused when it no longer fits; it is
not claimed as a speed-up.

## 3. Against the extension's waiting policy

| Scenario | Desk median / p95 (ms) | Extension policy median / p95 (ms) | Extension policy correct |
| --- | --- | --- | --- |
| Navigate and read a document's figures (two clicks) | 29.6 / 62.5 | 1064.0 / 1070.0 | 20/20 |
| Update information on the portal (one click) | 26.5 / 30.7 | 563.6 / 577.6 | 20/20 |
| The layout changed | 191.9 / 198.4 | 1063.1 / 1071.0 | 20/20 (Scriba's locator fallback found the links by their text) |
| A dialog is in the way | 34.7 / 37.5 | 10654.7 / 10655.9 | **0/3**: the click is swallowed, the next step waits its 10 s and the replay fails |

Almost all of the difference is the fixed 500 ms pause after each click. The
Desk replaces it with one short question to the page ("did a navigation
start?") and then waits for the new document only if one did.

Not compared, because the extension has no such thing at this revision:
downloading a file, searching a table across pages, reading a submission back,
taking up an interrupted replay. A form with a native dropdown cannot be
replayed by Scriba's player at all (its `select` step throws).

## 4. Parts of a task

| What | Median (ms) | p95 (ms) | n |
| --- | --- | --- | --- |
| Browser start, cold (process start to ready) | 98.8 | 159.6 | 5 |
| Opening a page (navigate until the document can be used) | 8.1 | 10.8 | 100 |
| Following a link (look up, check, click, wait for the next page) | 10.6 | 14.6 | 80 |
| Filling in one or two fields and checking them | 3.5 | 7.3 | 60 |

The very first browser start of a session on this machine took between 1.7
and 2.1 seconds in separate runs (cold disk); the five starts above came
after it. A new tab took about 60 to 125 ms.

## 5. What this does not show

- Nothing about a real site: no network, no heavy pages, no bot protection, no
  single sign-on, no frames.
- Nothing about a model: none was used, so nothing here says how a
  model-directed browser would do.
- One machine, one browser build, one synthetic site written by the same hand
  as the tool. A site built by someone else is the test that matters next
  (Agent 3).
