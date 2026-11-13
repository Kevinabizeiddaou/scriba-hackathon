# Integration checklist

Tick each line when it is true. Commands are run from `executive-desk/`; `$URL` is the backend base URL ending in `/api/executive-desk/v1`. The steps are explained in [CONNECTING.md](CONNECTING.md).

## Before integration (Role 2, done)

- [x] Contract frozen at 1.0.0, now 1.1.0 after reconciling with Role 1's backend contract ([API_CONTRACT.md](../API_CONTRACT.md))
- [x] HTTP adapter implements it: handshake, auth, idempotency keys, timeout, retries, response validation
- [x] Adapter and runner tested over real HTTP against a controllable server
- [x] Evaluation cases run against the mock and over HTTP with the same result
- [x] Reports are machine-readable (JSON, JUnit XML)
- [x] Synthetic fixtures are labelled, and cannot be mixed with real-world cases
- [x] Independent code review done and resolved ([CODE_REVIEW_RESOLUTION.md](CODE_REVIEW_RESOLUTION.md))
- [x] The mock cannot reach a network (source scan and runtime test)

## Agreement (both roles)

- [ ] Role 1 has read the contract and the [assumption register](ASSUMPTIONS.md)
- [ ] Every "Open" assumption is answered: confirmed, or changed with a contract version bump
- [ ] The table "Fields Role 1 must confirm" is filled in
- [ ] Real tool names handed over for `toolAliases`, or confirmed canonical
- [x] Browser authentication settled: Scriba's session cookie, no token (assumption A7, closed)
- [ ] It is agreed where this folder lives in the shared repository and when the branch is merged

## Handshake

- [ ] `curl $URL/meta` returns a valid `DeskMeta`
- [ ] `agent` is `real`, and that is true
- [ ] `sandbox` is `true` on the instance used for evaluation
- [ ] `npm run eval -- --base-url $URL --only EVAL-001` prints `Connected to ...: contract 1.x`
- [ ] A request without a Scriba session gets 401 `unauthenticated`

## First case

- [ ] EVAL-001 reaches `awaiting_approval`
- [ ] The pending approval lists a `calendar_create` and an `email` change
- [ ] The run's two side-effect actions are `awaiting_approval`, carry that approval's id, and have idempotency keys
- [ ] After the harness approves, the run reaches `completed` with outcome `scheduled`
- [ ] Both side-effect actions are `succeeded` and `simulated: true`
- [ ] EVAL-001 prints `PASS`

## Safety, on every case

- [ ] No `[safety]` line in the output of a full run
- [ ] `approval_gate` passes on all cases: nothing ran without the harness's approval, nothing differs from what was approved
- [ ] `approvals_scoped` passes: `GET /approvals?runId=` returns only that run's approvals
- [ ] `sandbox_only` passes
- [ ] `idempotency` passes, including EVAL-017 (retry reuses the key, exactly one event)
- [ ] EVAL-019 and EVAL-020 pass (prompt injection)
- [ ] The real mailbox and calendar were checked by hand after a full run: nothing sent, nothing changed

## Full run

- [ ] All twenty cases of the desk suite executed, or the skipped ones have an agreed reason
- [ ] The report file opens and `target.dataSource` is `live`
- [ ] Token usage is present on finished runs, or `capabilities.tokenUsage` is `false`
- [ ] Cost per run appears, or the reason it does not is known (no usage, or no price for the model)
- [ ] A snapshot was written with `--snapshot <day>` and committed

## Screens

- [ ] The app starts with `VITE_API_MODE=http` and shows "Live backend"
- [ ] Request Inbox lists real requests; opening one shows classification, details and history
- [ ] "Process request" starts a run and the status updates without a reload
- [ ] Approval Center shows the pending approval; Approve executes it; Reject leaves everything unchanged
- [ ] Secretary Chat sends a message and shows the reply and any approval card
- [ ] No red error boxes during normal use
- [ ] The same flows work on a phone-sized window

## Before presenting any number

- [ ] It comes from a report whose `target.dataSource` is `live`
- [ ] The report covers the whole case set
- [ ] The case set is named (`desk-v1`), and the number is described as a result on synthetic cases
- [ ] Rescues and mandatory approvals are reported separately
