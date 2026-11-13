# Connecting Role 1's backend

Exact steps, in order. Each step has a command and what you should see. Run everything from the `executive-desk/` folder.

You do not need to change frontend code to connect. The two places where backend-specific knowledge goes are both in `src/api/`:

| What | Where |
| --- | --- |
| Backend tool names that differ from the canonical ones | `DEFAULT_TOOL_ALIASES` in `src/api/httpAdapter.ts` |
| How the browser gets its token | `getToken` in `src/api/index.ts` |

## 0. Before you start

```bash
npm install
```

```bash
npm test
```

Expect every test to pass. This proves the frontend, the adapter and the runner are sound on their own, so anything that fails later is about the connection.

See the contract working end to end without any backend:

```bash
npm run dev:reference
```

That starts the reference server on port 8787 and the app on http://localhost:5184, talking to each other over real HTTP. Use the browser's network tab to see the exact requests and responses your backend will exchange. The sidebar says "Mock data" because the reference server reports a scripted agent.

## 1. Bring up the handshake

Implement `GET /meta` first ([contract section 3](../API_CONTRACT.md)).

```bash
curl -s http://localhost:8000/api/executive-desk/v1/meta
```

Expect JSON with `contractVersion` starting `1.`, `agent`, `sandbox`, `principal` and `capabilities`. Compare with the reference:

```bash
curl -s http://127.0.0.1:8787/api/executive-desk/v1/meta
```

Then let the client check it:

```bash
npm run eval -- --base-url http://localhost:8000/api/executive-desk/v1 --only EVAL-001
```

The first line it prints is the handshake result:

```
Connected to <service>: contract 1.0.0, agent real, sandbox true.
```

If it prints an error instead, the message names the problem: unreachable, wrong contract version, or the exact field of `/meta` that does not match.

With authentication, put the token in an environment variable and name the variable. Never pass the token itself as an argument.

```bash
DESK_TOKEN=... npm run eval -- --base-url http://localhost:8000/api/executive-desk/v1 --token-env DESK_TOKEN --only EVAL-001
```

## 2. Run one case

Implement `POST /evaluation/runs`, `GET /runs/{id}`, `GET /approvals` and `POST /approvals/{id}/decision` (requirements groups B and C).

```bash
npm run eval -- --base-url http://localhost:8000/api/executive-desk/v1 --only EVAL-001
```

What happens: the runner posts the case, polls the run, approves the pending approval as `evaluation-harness`, waits for the run to finish, and scores it.

| You see | Meaning |
| --- | --- |
| `EVAL-001  PASS` | The whole loop works |
| `EVAL-001  FAIL` followed by lines starting `x` | The run finished; each line is one check with expected and actual |
| `x [safety] ...` | A safety rule was broken (approval gate, sandbox, idempotency, recipients). Fix these first. |
| `EVAL-001  ERROR` followed by `! backend/contract_violation` | A response does not match the contract; the message lists the fields by path |
| `! backend/unknown_tool` | Add the tool name to `DEFAULT_TOOL_ALIASES` |
| `! harness/timeout` | The run did not reach a final status in 120 s, or a request hung. Check that the POST returns promptly and that the run leaves `awaiting_approval` after the decision. |
| `! harness/not_sandbox` | `/meta` says `sandbox: false`. The runner will not run cases there. |

The report is written to `eval-results/report-<timestamp>.json`. It contains the full run and approvals for each case, so you can see exactly what the runner received.

## 3. Map tool names

If the backend's tool names differ, add them once:

```ts
// src/api/httpAdapter.ts
export const DEFAULT_TOOL_ALIASES: Record<string, ToolName> = {
  gmail_send_message: 'email.send',
  // ...
};
```

The mapping applies to run actions and to approval changes. Re-run step 2.

## 4. Run all twenty

```bash
npm run eval -- --base-url http://localhost:8000/api/executive-desk/v1 --label "Friday first full run"
```

If fault injection is not ready, `/meta` should say `capabilities.faultInjection: false`; EVAL-017 and EVAL-018 are then skipped automatically, with the reason in the report.

To add cost when the backend reports tokens but not cost, write the real prices of the model in use to a file and pass it. See [COST_PER_RUN.md](../submission/COST_PER_RUN.md).

```bash
npm run eval -- --base-url http://localhost:8000/api/executive-desk/v1 --pricing prices.json
```

For CI, also write JUnit XML, or take the report on stdout:

```bash
npm run eval -- --base-url http://localhost:8000/api/executive-desk/v1 --junit eval-results/junit.xml
```

```bash
npm run eval -- --base-url http://localhost:8000/api/executive-desk/v1 --print-json > report.json
```

Exit code 0 means every executed case passed, 1 means at least one failed or errored, 2 means the run could not start.

## 5. Check by hand that nothing real happened

Once, after the first full run: open the real mailbox and calendar the backend is configured with, and confirm that no email was sent and no event changed. The runner checks the `simulated` flag on every side effect, but it can only see what the backend reports.

## 6. Freeze a day's snapshot

Only a complete run against a real agent can be a snapshot.

```bash
npm run eval -- --base-url http://localhost:8000/api/executive-desk/v1 --snapshot friday --label "Friday evening"
```

That writes `eval-results/snapshots/friday.json`. Commit it and the dashboard shows it. The command refuses if the target is scripted, if any case was skipped, or if every case errored.

## 7. Connect the screens

Implement requirements group D, then start the app against the backend:

```bash
VITE_API_MODE=http VITE_API_BASE_URL=http://localhost:8000/api/executive-desk/v1 npm run dev
```

On Windows PowerShell:

```powershell
$env:VITE_API_MODE='http'; $env:VITE_API_BASE_URL='http://localhost:8000/api/executive-desk/v1'; npm run dev
```

Open http://localhost:5183.

- The sidebar shows "Live backend" and the service name when `/meta` says `agent: "real"`, and "Mock data" otherwise.
- For local testing with a token, run this in the browser console and reload. The key is `executive-desk.token`; do not commit a token anywhere.

  ```js
  sessionStorage.setItem('executive-desk.token', '<token>')
  ```

- If a screen shows a red error box, the text is the adapter's error message. `contract_violation` messages list the fields to fix.
- The browser must be allowed by CORS (requirement A7). The dev origin is `http://localhost:5183`.

The Evaluation Dashboard's "Run evaluation" button runs the same twenty cases from the browser and stores the report in that browser. "Import results" loads a report file written by the command line.

## 8. When something disagrees with the contract

- If the backend cannot do what a requirement asks, do not work around it in the UI. Record it in [ASSUMPTIONS.md](ASSUMPTIONS.md) and agree a contract change: update `types.ts` and `validate.ts`, bump `CONTRACT_VERSION`, add a line to the change log.
- If a case's expectation looks wrong for a correct agent, say which check and why. The expectations live in `src/evaluation/fixtures/`, and a changed expectation means a new case-set id.

## Where the code lives

This workspace is on the branch `role2/frontend-evaluation` of `Kevinabizeiddaou/scriba-hackathon`, entirely inside `executive-desk/`. It touches nothing outside that folder, so it can be merged next to the backend without conflicts. It has not been merged into `main`; do that together.
