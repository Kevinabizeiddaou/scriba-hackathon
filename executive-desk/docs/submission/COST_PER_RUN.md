# Cost per run: calculation template

No cost has been measured yet. This file contains the method and blank tables. Every figure is to be filled in from a real evaluation report; nothing here is an estimate.

## Definition

One run is one request handled from trigger to final status, including every model call and every retry inside it.

```
AI cost of one run = for each model the run used, the sum of
      uncached input tokens  x  that model's input price per token
    + cached input tokens    x  that model's cached-input price per token
    + output tokens          x  that model's output price per token

AI cost per run = sum of the cost of every priced run / number of priced runs
```

The backend reports tokens per model in `AgentRun.usage.models[]`, summed over every call to that model in the run (`inputTokens` counts uncached input only; `cachedInputTokens` is separate). If the run used a model that has no price in the table, the run has no cost at all: a partial sum would look like a real cost while leaving part of the run out. Runs without a cost are left out of both the sum and the count, and the report says how many were priced (`casesWithCost`).

## Where the numbers come from

| Quantity | Source | Field |
| --- | --- | --- |
| Tokens per run, per model | Backend, per run | `AgentRun.usage.models[]` |
| Cost per run, if the backend computes it | Backend | `AgentRun.usage.estimatedCostUsd` |
| Prices, if the backend reports tokens only | The model provider's published price list on the day of the run | `--pricing prices.json` |
| Cost per run across the suite | Evaluation report | `summary.costPerRunUsd`, `summary.totalCostUsd`, `summary.casesWithCost` |
| Which source each case used | Evaluation report | `results[].costSource` (`backend` or `price_table`) |

The price table ships empty (`src/evaluation/pricing.ts`). To use one, create a file like this with the real model name and the provider's current prices in USD per million tokens, and pass it with `--pricing`:

```json
{
  "<model name exactly as the backend reports it>": {
    "inputPerMTokUsd": null,
    "outputPerMTokUsd": null,
    "cachedInputPerMTokUsd": null
  }
}
```

The nulls are placeholders, and the runner refuses a table that still contains them. Replace all three with the provider's numbers before running, and write down the date and the page they were taken from.

## Fill-in sheet

Run: ______________________  Date: ______________  Report file: ______________________

| Line | Quantity | Value |
| --- | --- | --- |
| a | Model | |
| b | Price source and date | |
| c | Cases executed | |
| d | Cases with reported usage (`casesWithUsage`) | |
| e | Cases with a cost (`casesWithCost`) | |
| f | Total input tokens, cached included (`totalInputTokens`) | |
| g | Total output tokens (`totalOutputTokens`) | |
| h | Total AI cost in USD (`totalCostUsd`) | |
| i | **AI cost per run in USD (`costPerRunUsd` = h / e)** | |
| j | Most expensive case and its cost | |
| k | Cheapest case and its cost | |

## Cost per successful run

Cost per run counts every run, including failures. If the submission asks for the cost of a successful outcome, report this as well:

```
AI cost per unassisted pass = total AI cost (line h) / cases passed unassisted
```

| Line | Quantity | Value |
| --- | --- | --- |
| l | Cases passed unassisted (`passedUnassisted`) | |
| m | AI cost per unassisted pass in USD (h / l) | |

## Human time, reported separately

Approvals are part of the design, so their time is a cost of the product, not of the model. Measure it; do not assume it.

| Line | Quantity | How to measure | Value |
| --- | --- | --- | --- |
| n | Mandatory approvals across the suite (`mandatoryApprovals`) | Evaluation report | |
| o | Median seconds a person takes to review one approval | Time real approvals in the Approval Center with a stopwatch, at least ten | |
| p | Rescues (`rescued`) | Evaluation report | |

## What is not included

- Gmail and Google Calendar API usage, hosting, storage and monitoring. If the challenge asks for full running cost, add them as separate lines with their own sources.
- Runs made during development outside the evaluation.

## Checks before publishing a number

- [ ] The report's `target.dataSource` is `live`.
- [ ] `casesWithCost` equals the number of cases executed, or the gap is explained.
- [ ] Prices match the provider's page on the date of the run, for the exact model.
- [ ] The figure quoted is `costPerRunUsd` from the report, not a hand calculation.
