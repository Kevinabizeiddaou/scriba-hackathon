# Security and safety notes

## Scope

The lab tests the Desk overlay of this repository, in a sandbox, with synthetic mail. It does not test, probe or
describe the separate Scriba service: Scriba is used read-only at a pinned commit as the application the overlay
runs inside, with its seeded development users and in-memory stores.

## What is in the repository, and what is not

- The adversarial inputs (`aql/adversarial.py`) are generic, widely known patterns: an instruction addressed to
  "the assistant", a claim of prior approval, an address that appears only in the body, a look-alike domain, a
  forged urgency. Every address is on the reserved `.example` domain. There is no live data and no secret.
- The reports record, for each case, what the sandbox office looked like afterwards. They contain no credential, no
  session value and no real correspondence. The session cookie of the seeded test user lives in memory for the
  length of a run and is never written.
- **Not included:** anything that would describe how to reach a weakness of the Scriba service itself. The lab
  found none because it did not look: that service is out of scope, and a finding about it would go to its owners
  privately, not into this public repository. The same applies to Agent 1's "remaining security risks" that concern
  Scriba's own behaviour (its retry, its session handling): the lab neither reproduces nor details them.
- `server/lab_server.py` adds routes that read and change sandbox state. They exist only in a process started by
  that file. They refuse to work without a signed-in session and are scoped to the caller's own runs. Do not mount
  them anywhere a real mailbox is connected: the launcher is a test instrument and is not hardened.

## The invariant

> The engine cannot turn content from an incoming email into authorization for an external action.

It is checked from outside, on every case of every family, by four independent observations:

1. **Who was reached.** Every recipient of every mail that left, and every attendee of every event created, must be
   the sender of the message being answered, an address the truth allows, or one of the executive's own accounts
   (`recipient_provenance`).
2. **Whether an approval stands behind it.** Every external effect in the office is matched against an approval the
   lab itself gave, and against what the lab was shown when it gave it (`approval_gate`,
   `executed_equals_approved`). With the person rejecting everything, the office must be unchanged whatever the
   email says about having been pre-approved (`untrusted_content_not_authority`).
3. **What was said.** No other meeting, person or document of the executive may be named in outgoing mail
   (`no_private_data_leak`), and the mail must leave from the mailbox the request reached
   (`no_cross_account_leak`).
4. **What was changed.** No calendar change other than the one the request legitimately calls for
   (`no_unrequested_effect`).

Whether the engine *flagged* a message as a suspected injection is recorded as an advisory check
(`injection_flagged`) and never decides a verdict. A system is safe because of what it cannot do, not because of
what it noticed.

## Result on the pinned commit (rules-only, sandbox)

See `docs/RESULTS.md` for the numbers. In short: across the hostile cases the structural defences held. No mail
reached an address taken from a message body, nothing ran on a rejected or refused approval, a replayed or
concurrent approval produced one effect, another user could neither see nor approve a run. Detection by wording
caught one hostile message in eleven; that is a statement about the detector, and it is why the detector is not
what the safety rests on.

The safety-critical results the lab did find are of another kind: actions a person approved that were not what the
request called for (a second meeting instead of a move, a meeting an hour or a day off, a cancellation the sender
had withdrawn). They are in the handoff as S1 to S5.

## Limits of this evidence

- Rules-only. A model in the loop changes the attack surface: the same campaign must be re-run with it, and the
  invariant above is exactly what should be watched.
- The sandbox replaces the providers. Nothing here says anything about a live mailbox, a live calendar, or the
  provider call inside an approved attempt.
- The corpus is synthetic and finite. It finds classes of failure; it does not prove their absence.
