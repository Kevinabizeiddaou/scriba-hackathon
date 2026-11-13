# Real-world evaluation cases

This folder is empty on purpose. It is where cases derived from real requests go, if and when there are any. There are none today: every case the harness ships with is a synthetic fixture.

Synthetic fixtures and real-world cases are kept apart so that a result can always say which it is about.

| | Synthetic fixtures | Real-world cases |
| --- | --- | --- |
| File | `fixtures/evaluation-cases.json` (generated from `src/evaluation/fixtures/`) | one file per set in this folder |
| `caseSet.provenance` | `synthetic` | `real_world` |
| Case ids | `EVAL-001` to `EVAL-020` (the `EVAL-nnn` form is reserved) | anything else, for example `REAL-001` |
| People and addresses | invented, on the `.example` domain | anonymised, on the `.example`, `.test` or `.invalid` domain |
| Per-case `provenance` | `{ "kind": "synthetic", "note": ... }` | `{ "kind": "real_world", "source": ..., "anonymized": true, "consentReference": ... }` |

## Rules for adding a real-world case

1. Get the person's agreement to use the request, and record where that agreement is kept. That reference goes in `consentReference`.
2. Anonymise it: replace every name, company, address and identifying detail. Keep the structure that makes the case interesting (the wording of the request, the shape of the calendar, the time zones).
3. Use only reserved domains for addresses. The loader refuses a file that contains any other address.
4. Write the expected behaviour as carefully as for a synthetic case. A real request with a vague expectation teaches nothing.
5. Never commit the original email, a screenshot of it, or anything copied from a production mailbox or calendar.

## Running a set

```bash
npm run eval -- --base-url <backend> --cases fixtures/real-world/<file>.json
```

The loader (`src/evaluation/caseSets.ts`) refuses a file when a case has no provenance, when a set mixes the two kinds, when a real-world case is not marked anonymised or has no consent reference, when it reuses an `EVAL-nnn` id, or when it contains an address outside the reserved domains. The report records the set's id and provenance, and every result carries its case's provenance.

A real-world set is reported on its own. Its pass rate is never combined with the synthetic set's.

## File format

```json
{
  "format": "executive-desk.case-set/1",
  "notice": "Anonymised cases from ...",
  "contractVersion": "1.0.0",
  "caseSet": { "id": "<set id>", "provenance": "real_world", "caseCount": 1 },
  "cases": [ { "id": "REAL-001", "provenance": { "kind": "real_world", "source": "...", "anonymized": true, "consentReference": "..." }, "...": "the rest of an EvaluationCase" } ]
}
```
