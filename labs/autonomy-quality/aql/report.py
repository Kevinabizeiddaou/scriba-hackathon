"""Markdown and static HTML renderings of a campaign report.

The JSON report is the source of truth; these are views of it. Neither view
adds a number that is not in the JSON, and both carry the evidence statement
at the top: what kind of engine produced these results.
"""
from __future__ import annotations

import html
from typing import Any, Dict, List, Optional


def pct(value: Optional[float]) -> str:
    return "not measured" if value is None else f"{value * 100:.1f}%"


def ms(value: Optional[float]) -> str:
    return "not measured" if value is None else (f"{value / 1000:.2f} s" if value >= 1000 else f"{value:.0f} ms")


def _trace_line(report: Dict[str, Any]) -> str:
    key = report["traceability"]
    return (f"backend `{str(key['backendCommit'])[:12]}` · runner `{key['runnerVersion']}` · seed `{key['seed']}` · "
            f"model `{key['model'] or 'none'}` · mode `{key['executionMode']}`")


def render_markdown(report: Dict[str, Any]) -> str:
    s, target = report["summary"], report["target"]
    out: List[str] = []
    add = out.append
    add(f"# Autonomy Quality Lab: {report['label']}")
    add("")
    add(f"**{report['evidence']['statement']}**")
    add("")
    add(f"Traceability: {_trace_line(report)}")
    add(f"Run {report['startedAt'][:19]}Z to {report['finishedAt'][:19]}Z, {report['runner']['repeat']} pass(es), "
        f"contract {target['contractVersion']}, overlay {target['overlayVersion']}, Scriba `{str(target['scribaCommit'])[:8]}` (read-only).")
    add("")
    add("## What kind of evidence this is")
    add("")
    add("| Class | Measured here | Note |")
    add("| --- | --- | --- |")
    for name in ("rules_only", "scripted_model", "real_model", "isolated_provider_sandbox", "live_provider"):
        row = report["evidence"][name]
        add(f"| {name.replace('_', ' ')} | {'yes' if row['measured'] else '**no**'} | {row['note']} |")
    add("")
    add("## Headline")
    add("")
    add("| Measure | Value | Over |")
    add("| --- | --- | --- |")
    add(f"| Complete job success rate | **{pct(s['completeJobSuccessRate'])}** | {s['cases']} cases, none excluded |")
    add(f"| ...excluding inputs the backend cannot take at all | {pct(s['completeJobSuccessRateExcludingUnsupported'])} | "
        f"{s['cases'] - s['byVerdict'].get('unsupported', 0) - s['byVerdict'].get('error', 0)} cases |")
    add(f"| Completed or safely handed to the person | {pct(s['completedOrSafelyHandedOver'])} | {s['cases']} |")
    add(f"| Correct intent | {pct(s['correctIntentRate'])} | {s['correctIntentDenominator']} |")
    add(f"| Correct final state | {pct(s['correctFinalStateRate'])} | {s['correctFinalStateDenominator']} |")
    add(f"| Safety violations | **{s['safetyViolations']}** ({pct(s['safetyViolationRate'])}) | {s['cases']} |")
    add(f"| False successes (filed as done, job not done) | **{s['falseSuccesses']}** ({pct(s['falseSuccessRate'])}) | {s['cases']} |")
    add(f"| Mandatory approvals | {s['mandatoryApprovals']} ({s['mandatoryApprovalsPerCompletedJob']} per completed job) | |")
    add(f"| Human rescues | {s['humanRescues']} ({s['humanRescuesPerCompletedJob']} per completed job) | |")
    lat = s["latencyMs"]
    add(f"| Latency, median / p90 / p95 / max | {ms(lat['median'])} / {ms(lat['p90'])} / {ms(lat['p95'])} / {ms(lat['max'])} | lab wall clock, approvals included |")
    add(f"| Cost per run | {('$%.4f' % s['cost']['perRunUsd']) if s['cost']['perRunUsd'] is not None else s['cost']['note']} | |")
    c = report["consistency"]
    add(f"| Repeated-run consistency | {pct(c.get('consistencyRate')) if c.get('measured') else c.get('note')} | "
        f"{c.get('cases', '')} cases x {c.get('repeats')} |")
    add("")
    add("Verdicts: " + ", ".join(f"{name} {count}" for name, count in sorted(s["byVerdict"].items())) + ".")
    add("")
    add("A mandatory approval is not a failure of autonomy; it is counted on its own line. A rescue is anything else "
        "the lab had to do for the engine (a retry, an advance).")
    add("")
    add("## Quality gates")
    add("")
    add("| Gate | Status | Checks evaluated | Violations | Cases |")
    add("| --- | --- | --- | --- | --- |")
    for gate in report["gates"]["hard"]:
        mark = {"pass": "PASS", "fail": "**FAIL**", "not_evaluated": "not evaluated"}[gate["status"]]
        cases = ", ".join(gate["violatingCases"][:6]) + (" ..." if len(gate["violatingCases"]) > 6 else "")
        add(f"| {gate['title']}{' (lab-defined)' if gate['labDefined'] else ''} | {mark} | {gate['checksEvaluated']} | {gate['violations']} | {cases} |")
    add("")
    add("Advisory thresholds (reported, never blocking):")
    add("")
    add("| Measure | Target | Value | Status |")
    add("| --- | --- | --- | --- |")
    for row in report["gates"]["advisory"]:
        value = row["value"]
        shown = "not measured" if value is None else (pct(value) if isinstance(value, float) and value <= 1 and "Ms" not in row["id"] and "cost" not in row["id"] else str(value))
        add(f"| {row['label']} | {'>=' if row['direction'] == 'min' else '<='} {row['target']} | {shown} | {row['status'].replace('_', ' ')} |")
    add("")
    for family, title in (("semantic", "Semantic robustness corpus"), ("metamorphic", "Metamorphic members"),
                          ("adversarial", "Adversarial cases"), ("scenario", "Product-route scenarios")):
        row = report["byFamily"].get(family)
        if not row:
            continue
        add(f"- **{title}**: {row['cases']} run, {row['byVerdict'].get('completed', 0)} completed, "
            f"{row['byVerdict'].get('safe_handoff', 0)} handed over, {row['byVerdict'].get('failed', 0)} failed, "
            f"{row['byVerdict'].get('unsafe', 0)} unsafe, {row['byVerdict'].get('unsupported', 0)} unsupported, "
            f"{row['byVerdict'].get('error', 0)} lab errors.")
    add("")
    if report["byCategory"]:
        add("## Success by workflow category (semantic corpus)")
        add("")
        add("| Category | Cases | Completed | Handed over | Failed | Unsafe | Other | False success | Intent correct |")
        add("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for name, row in report["byCategory"].items():
            add(f"| {name} | {row['cases']} | {row['completed']} ({pct(row['successRate'])}) | {row['safeHandoff']} | {row['failed']} | "
                f"{row['unsafe']} | {row['other']} | {row['falseSuccess']} | {row['intentCorrect']} |")
        add("")
        add("By language (a measurement, not a statement of support):")
        add("")
        add("| Language | Cases | Completed | Handed over | Failed | Unsafe |")
        add("| --- | --- | --- | --- | --- | --- |")
        for name, row in report["byLanguage"].items():
            add(f"| {name} | {row['cases']} | {row['completed']} | {row['safeHandoff']} | {row['failed']} | {row['unsafe']} |")
        add("")
    meta = report["metamorphic"]
    if meta["relations"]:
        add("## Metamorphic relations")
        add("")
        add(f"{meta['hold']} of {meta['relations']} relations hold; {meta['broken']} are broken.")
        add("")
        add("| Relation | Relations | Hold | Broken | Follow-up cases | Follow-ups breaking it |")
        add("| --- | --- | --- | --- | --- | --- |")
        for name, row in meta["byRelation"].items():
            add(f"| {name} | {row['relations']} | {row['hold']} | {row['broken']} | {row['followUps']} | {row['followUpsBroken']} |")
        add("")
        broken = [r for r in meta["results"] if r["holds"] is False]
        if broken:
            add("Broken relations:")
            add("")
            for relation in broken:
                add(f"- `{relation['id']}` ({relation['title']}; expected: {relation['expect']}; base verdict {relation['baseVerdict']})")
                for follow in relation["followUps"]:
                    if follow["holds"] is False:
                        add(f"  - `{follow['id']}`: {follow['why']}")
            add("")
    if report["adversarialByCategory"]:
        add("## Adversarial and scenario results by category")
        add("")
        add("| Category | Cases | Completed | Handed over | Failed | Unsafe | Other |")
        add("| --- | --- | --- | --- | --- | --- | --- |")
        for name, row in report["adversarialByCategory"].items():
            add(f"| {name} | {row['cases']} | {row['completed']} | {row['safeHandoff']} | {row['failed']} | {row['unsafe']} | {row['other']} |")
        add("")
    add("## Root causes")
    add("")
    add("One row per defect, not per wording. Details, reproductions and acceptance criteria: `ROOT_CAUSES.md`.")
    add("")
    add("| # | Root cause | Severity | Cases | Classes |")
    add("| --- | --- | --- | --- | --- |")
    for index, cause in enumerate(report["rootCauses"], 1):
        add(f"| {index} | {cause['title']} (`{cause['rootCause']}`) | {cause['severity'].replace('_', ' ')} | {cause['affectedCases']} | {', '.join(cause['classes'])} |")
    add("")
    if report["missingEndpoints"]:
        add("## What the backend does not offer")
        add("")
        for missing in report["missingEndpoints"]:
            add(f"- `{missing['endpoint']}`: needed for {missing['neededFor']}.")
        add("")
    unsafe = [r for r in report["results"] if r["verdict"] == "unsafe"]
    if unsafe:
        add("## Safety-critical results")
        add("")
        add("| Case | Failed safety checks | What the office shows |")
        add("| --- | --- | --- |")
        for result in unsafe:
            actual = "; ".join(c["actual"] for c in result["checks"] if c["passed"] is False and c["safety"])[:220]
            add(f"| `{result['id']}` | {', '.join(result['safetyFailures'])} | {actual} |")
        add("")
    add("Case by case, for everything not completed: `CASES.md`. Full traces (input, the lab's decisions, the engine's "
        "record, the office afterwards) for every case: `traces.jsonl.gz`.")
    add("")
    return "\n".join(out)


def render_root_causes(report: Dict[str, Any]) -> str:
    out: List[str] = [f"# Root causes: {report['label']}", "", report["evidence"]["statement"], "",
                      f"Traceability: {_trace_line(report)}", "",
                      "Failures are grouped by cause. Each group has one minimal reproduction; the other affected "
                      "cases are listed by id and each has a trace file.", ""]
    for index, cause in enumerate(report["rootCauses"], 1):
        rep = cause["reproduction"]
        out += [f"## {index}. {cause['title']}", "",
                f"`{cause['rootCause']}` · severity **{cause['severity'].replace('_', ' ')}** · {cause['affectedCases']} cases · "
                f"{', '.join(cause['classes'])}", "",
                f"**Owner:** {cause['owner']}" + (f" · **Where:** {cause['where']}" if cause.get("where") else ""), "",
                "**Reproduce**", "", "```", rep["command"], "```", "",
                f"Input (`{rep['caseId']}`, seed {rep['seed']}, clock {rep['input']['now']}):", "",
                f"- From: {rep['input']['from']}", f"- Subject: {rep['input']['subject']}",
                "- Body: " + " ".join(str(rep['input']['bodyText'] or '').split())[:600]]
        if rep["input"].get("threadMessages"):
            out.append(f"- Earlier messages in the thread: {rep['input']['threadMessages']}")
        if rep["input"].get("script"):
            out.append(f"- What the person or the outside world does: `{rep['input']['script']}`")
        out += ["", f"**Expected:** {cause['expected']}", "", f"**Actual:** {cause['actual']}", "",
                f"**The engine said:** classification `{cause['engineSaid'].get('classification')}`, outcome "
                f"`{cause['engineSaid'].get('outcome')}`, stage `{cause['engineSaid'].get('lifecycle')}`, held "
                f"`{cause['engineSaid'].get('held')}`."]
        trace = cause["trace"]
        if trace.get("decision"):
            out.append(f"Its decision: \"{trace['decision']}\"")
        if trace.get("understanding"):
            u = trace["understanding"]
            out.append(f"Its reading: category `{u.get('category')}`, reasons `{u.get('reasons')}`, source `{u.get('source')}`.")
        if trace.get("actions"):
            out.append("Its actions: " + ", ".join(f"{tool} {status}" for tool, status in trace["actions"]) + ".")
        out += ["", f"**Suggested correction:** {cause['suggestedCorrection']}", "", "**Regression acceptance criteria:**", ""]
        out += [f"- {line}" for line in cause["acceptance"]]
        out += ["", f"**Affected cases ({cause['affectedCases']}):** " + ", ".join(f"`{c}`" for c in cause["caseIds"]), ""]
    return "\n".join(out)


def render_cases(report: Dict[str, Any], full: List[Dict[str, Any]]) -> str:
    """One section per case that was not completed: the input, what was
    expected, what the engine said, what the office shows."""
    out: List[str] = [f"# Case by case: {report['label']}", "", report["evidence"]["statement"], "",
                      f"Traceability: {_trace_line(report)}", "",
                      "Every case that did not end `completed`, in the order it ran. The complete trace of every case, "
                      "completed ones included, is in `traces.jsonl.gz` (one JSON object per line; "
                      "`python -m aql trace --report <dir> --case <id>` prints one).", ""]
    for result in full:
        if result["verdict"] == "completed":
            continue
        case = result.get("_case") or {}
        email = (case.get("input") or {}).get("email") or {}
        truth = case.get("truth") or {}
        trace = result.get("trace") or {}
        claimed = result.get("claimed") or {}
        out += [f"## `{result['id']}`: {result['verdict'].replace('_', ' ')}", "",
                f"{result.get('title') or ''} · category `{result.get('category')}` · root cause `{result.get('rootCause')}`"
                + (" · **false success**" if result.get("falseSuccess") else "")
                + (f" · instrumented: {', '.join(result['instrumented'])}" if result.get("instrumented") else ""), ""]
        if email:
            out += [f"- From: {(email.get('from') or {}).get('email')}", f"- Subject: {email.get('subject')}",
                    "- Body: " + " ".join(str(email.get("bodyText") or "").split())[:500]]
            thread = (case.get("input") or {}).get("thread") or []
            if thread:
                out.append(f"- Thread: {len(thread)} earlier message(s); the last: \"" +
                           " ".join(str(thread[-1].get('bodyText') or '').split())[:200] + "\"")
        if case.get("script"):
            out.append(f"- Script: `{json_short(case['script'])}`")
        if truth:
            jobs = truth.get("anyOf") or [truth.get("jobs") or []]
            wanted = " OR ".join(" + ".join(j["kind"] for j in alternative) for alternative in jobs)
            out.append(f"- Truth: {wanted}; intent one of {truth.get('intents')}")
        out.append(f"- Engine: classification `{result['intent'].get('actual')}`, outcome `{claimed.get('outcome')}`, "
                   f"stage `{claimed.get('lifecycle')}`, held `{claimed.get('held')}`, approvals given "
                   f"{result['human']['mandatoryApprovals']}, rescues {result['human']['rescues']}")
        actions = [(a.get("tool"), a.get("status")) for a in (trace.get("run") or {}).get("actions") or [] if a.get("sideEffect")
                   or a.get("tool") in ("task.create", "reminder.create")]
        if actions:
            out.append("- Its actions: " + ", ".join(f"{tool} {status}" for tool, status in actions))
        for item in result["checks"]:
            if item["passed"] is False:
                out.append(f"- FAILED `{item['id']}`{' (safety)' if item['safety'] else ''} [{item['evidence']}]: "
                           f"expected {item['expected']}; actual {item['actual']}")
        for error in result.get("errors") or []:
            out.append(f"- {error.get('code')}: {error.get('message')}")
        out.append("")
    return "\n".join(out)


def json_short(value: Any) -> str:
    import json

    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= 300 else text[:297] + "..."


def render_html(report: Dict[str, Any]) -> str:
    e = html.escape
    s = report["summary"]
    key = report["traceability"]

    def tile(label: str, value: str, tone: str = "") -> str:
        return f'<div class="tile {tone}"><div class="v">{e(value)}</div><div class="l">{e(label)}</div></div>'

    def bar(row: Dict[str, Any]) -> str:
        total = max(1, row["cases"])
        parts = [("ok", row["completed"]), ("hand", row["safeHandoff"]), ("fail", row["failed"]), ("unsafe", row["unsafe"]), ("other", row["other"])]
        return '<div class="bar">' + "".join(
            f'<span class="{name}" style="width:{count / total * 100:.2f}%" title="{name}: {count}"></span>' for name, count in parts if count) + "</div>"

    gates = "".join(
        f'<tr class="g-{g["status"]}"><td>{e(g["title"])}{" <em>(lab-defined)</em>" if g["labDefined"] else ""}</td>'
        f'<td class="st">{e(g["status"].replace("_", " ").upper())}</td><td>{g["checksEvaluated"]}</td><td>{g["violations"]}</td>'
        f'<td class="ids">{e(", ".join(g["violatingCases"][:8]))}{" ..." if len(g["violatingCases"]) > 8 else ""}</td></tr>'
        for g in report["gates"]["hard"])
    categories = "".join(
        f'<tr><td>{e(name)}</td><td>{row["cases"]}</td><td>{bar(row)}</td><td>{row["completed"]}</td><td>{row["safeHandoff"]}</td>'
        f'<td>{row["failed"]}</td><td>{row["unsafe"]}</td><td>{row["falseSuccess"]}</td></tr>'
        for name, row in report["byCategory"].items())
    adversarial = "".join(
        f'<tr><td>{e(name)}</td><td>{row["cases"]}</td><td>{bar(row)}</td><td>{row["completed"]}</td><td>{row["safeHandoff"]}</td>'
        f'<td>{row["failed"]}</td><td>{row["unsafe"]}</td><td></td></tr>'
        for name, row in report["adversarialByCategory"].items())
    relations = "".join(
        f'<tr><td>{e(name)}</td><td>{row["relations"]}</td><td>{row["hold"]}</td><td class="{"bad" if row["broken"] else ""}">{row["broken"]}</td>'
        f'<td>{row["followUps"]}</td><td>{row["followUpsBroken"]}</td></tr>'
        for name, row in report["metamorphic"]["byRelation"].items())
    causes = "".join(
        f'<tr><td>{i}</td><td><strong>{e(c["title"])}</strong><br><code>{e(c["rootCause"])}</code></td>'
        f'<td class="sev-{c["severity"]}">{e(c["severity"].replace("_", " "))}</td><td>{c["affectedCases"]}</td>'
        f'<td>{e(", ".join(c["classes"]))}</td><td><code>{e(c["reproduction"]["caseId"])}</code></td></tr>'
        for i, c in enumerate(report["rootCauses"], 1))
    rows = "".join(
        f'<tr class="v-{r["verdict"]}" data-v="{r["verdict"]}" data-f="{e(str(r.get("family")))}"><td><code>{e(r["id"])}</code></td>'
        f'<td>{e(str(r.get("category")))}</td><td class="vd">{e(r["verdict"].replace("_", " "))}</td>'
        f'<td>{e(str(r["intent"].get("actual")))}{"" if r["intent"].get("correct") in (True, None) else " ✗"}</td>'
        f'<td>{e(str((r.get("claimed") or {}).get("outcome")))}</td><td>{r["human"]["mandatoryApprovals"]}</td>'
        f'<td>{"yes" if r.get("falseSuccess") else ""}</td><td><code>{e(str(r.get("rootCause") or ""))}</code></td>'
        f'<td class="why">{e("; ".join(c["actual"] for c in r["checks"] if c["passed"] is False and c["id"] != "intent_understood")[:200])}</td></tr>'
        for r in report["results"])
    evidence = "".join(
        f'<tr><td>{e(name.replace("_", " "))}</td><td class="{"yes" if report["evidence"][name]["measured"] else "no"}">'
        f'{"measured" if report["evidence"][name]["measured"] else "NOT MEASURED"}</td><td>{e(report["evidence"][name]["note"])}</td></tr>'
        for name in ("rules_only", "scripted_model", "real_model", "isolated_provider_sandbox", "live_provider"))
    lat = s["latencyMs"]
    cons = report["consistency"]
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Autonomy Quality Lab</title>
<style>
:root{{--bg:#f6f5f1;--card:#fff;--ink:#1c1b19;--mute:#6b675f;--line:#dedad0;--ok:#2f7d4f;--hand:#3b6ea5;--fail:#b7791f;--unsafe:#b3261e;--other:#8a8578;--accent:#1f3a5f}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#16171a;--card:#1f2125;--ink:#ecebe7;--mute:#a09c93;--line:#34373d;--ok:#5fbf85;--hand:#7fb0e6;--fail:#e0a94a;--unsafe:#f0766c;--other:#8f8b82;--accent:#9cc0ee}}}}
:root[data-theme="dark"]{{--bg:#16171a;--card:#1f2125;--ink:#ecebe7;--mute:#a09c93;--line:#34373d;--ok:#5fbf85;--hand:#7fb0e6;--fail:#e0a94a;--unsafe:#f0766c;--other:#8f8b82;--accent:#9cc0ee}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:1180px;margin:0 auto;padding:28px 16px 64px}}h1{{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}}h2{{font-size:18px;margin:36px 0 10px}}
.sub{{color:var(--mute);margin:0 0 6px}}.banner{{border-left:4px solid var(--accent);background:var(--card);padding:12px 14px;margin:16px 0;border-radius:4px;font-weight:600}}
code{{font:12.5px ui-monospace,Consolas,monospace}}.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 14px}}.tile .v{{font-size:24px;font-weight:700;font-variant-numeric:tabular-nums}}
.tile .l{{color:var(--mute);font-size:12.5px}}.tile.bad .v{{color:var(--unsafe)}}.tile.warn .v{{color:var(--fail)}}.tile.good .v{{color:var(--ok)}}
.wrap{{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:8px}}table{{border-collapse:collapse;width:100%;font-size:13.5px}}
th,td{{text-align:left;padding:7px 10px;border-bottom:1px solid var(--line);vertical-align:top}}th{{color:var(--mute);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.04em;white-space:nowrap}}
tr:last-child td{{border-bottom:0}}td{{font-variant-numeric:tabular-nums}}.bar{{display:flex;height:10px;min-width:140px;border-radius:5px;overflow:hidden;background:var(--line)}}
.bar .ok{{background:var(--ok)}}.bar .hand{{background:var(--hand)}}.bar .fail{{background:var(--fail)}}.bar .unsafe{{background:var(--unsafe)}}.bar .other{{background:var(--other)}}
.g-pass .st{{color:var(--ok);font-weight:700}}.g-fail .st{{color:var(--unsafe);font-weight:700}}.g-not_evaluated .st{{color:var(--mute)}}.ids{{font-size:12px;color:var(--mute)}}
.yes{{color:var(--ok);font-weight:600}}.no{{color:var(--unsafe);font-weight:700}}.bad{{color:var(--unsafe);font-weight:700}}
.sev-safety{{color:var(--unsafe);font-weight:700}}.sev-false_success{{color:var(--fail);font-weight:700}}.sev-missed_work{{color:var(--fail)}}.sev-handoff{{color:var(--hand)}}
.v-completed .vd{{color:var(--ok)}}.v-safe_handoff .vd{{color:var(--hand)}}.v-failed .vd{{color:var(--fail)}}.v-unsafe .vd{{color:var(--unsafe);font-weight:700}}.v-unsupported .vd,.v-error .vd{{color:var(--other)}}
.why{{color:var(--mute);font-size:12.5px;max-width:360px}}.legend{{display:flex;gap:14px;flex-wrap:wrap;color:var(--mute);font-size:12.5px;margin:6px 0 10px}}
.legend i{{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px}}.filters{{display:flex;gap:8px;flex-wrap:wrap;margin:0 0 10px}}
.filters button{{font:inherit;font-size:13px;padding:4px 10px;border:1px solid var(--line);background:var(--card);color:var(--ink);border-radius:999px;cursor:pointer}}
.filters button[aria-pressed="true"]{{background:var(--accent);color:var(--bg);border-color:var(--accent)}}
</style></head><body><main>
<h1>Autonomy Quality Lab</h1>
<p class="sub">{e(report['label'])} · backend <code>{e(str(key['backendCommit'])[:12])}</code> · runner <code>{e(key['runnerVersion'])}</code> · seed <code>{key['seed']}</code> · model <code>{e(str(key['model'] or 'none'))}</code> · mode <code>{e(key['executionMode'])}</code></p>
<div class="banner">{e(report['evidence']['statement'])}</div>
<div class="tiles">
{tile('complete job success', pct(s['completeJobSuccessRate']), 'warn' if (s['completeJobSuccessRate'] or 0) < .8 else 'good')}
{tile('completed or safely handed over', pct(s['completedOrSafelyHandedOver']))}
{tile('correct intent', pct(s['correctIntentRate']))}
{tile('safety violations', str(s['safetyViolations']), 'bad' if s['safetyViolations'] else 'good')}
{tile('false successes', str(s['falseSuccesses']), 'bad' if s['falseSuccesses'] else 'good')}
{tile('cases run', str(s['cases']))}
{tile('mandatory approvals', str(s['mandatoryApprovals']))}
{tile('human rescues', str(s['humanRescues']))}
{tile('median latency', ms(lat['median']))}
{tile('p95 latency', ms(lat['p95']))}
{tile('cost per run', ('$%.4f' % s['cost']['perRunUsd']) if s['cost']['perRunUsd'] is not None else 'not measured')}
{tile('run-to-run consistency', pct(cons.get('consistencyRate')) if cons.get('measured') else 'not measured')}
</div>
<h2>What kind of evidence this is</h2>
<div class="wrap"><table><tr><th>Class</th><th>Status</th><th>Note</th></tr>{evidence}</table></div>
<h2>Quality gates</h2>
<div class="wrap"><table><tr><th>Gate</th><th>Status</th><th>Checks</th><th>Violations</th><th>Cases</th></tr>{gates}</table></div>
<h2>Success by workflow category</h2>
<div class="legend"><span><i style="background:var(--ok)"></i>completed</span><span><i style="background:var(--hand)"></i>safely handed over</span><span><i style="background:var(--fail)"></i>failed</span><span><i style="background:var(--unsafe)"></i>unsafe</span><span><i style="background:var(--other)"></i>unsupported / error</span></div>
<div class="wrap"><table><tr><th>Category</th><th>Cases</th><th></th><th>Completed</th><th>Handed over</th><th>Failed</th><th>Unsafe</th><th>False success</th></tr>{categories}
<tr><th colspan="8">Adversarial cases and product-route scenarios</th></tr>{adversarial}</table></div>
<h2>Metamorphic relations: {report['metamorphic']['hold']} of {report['metamorphic']['relations']} hold</h2>
<div class="wrap"><table><tr><th>Relation</th><th>Relations</th><th>Hold</th><th>Broken</th><th>Follow-up cases</th><th>Breaking</th></tr>{relations}</table></div>
<h2>Root causes</h2>
<div class="wrap"><table><tr><th>#</th><th>Root cause</th><th>Severity</th><th>Cases</th><th>Classes</th><th>Reproduce with</th></tr>{causes}</table></div>
<h2>Every result</h2>
<div class="filters" id="filters"><button data-v="" aria-pressed="true">all</button><button data-v="unsafe" aria-pressed="false">unsafe</button><button data-v="failed" aria-pressed="false">failed</button><button data-v="safe_handoff" aria-pressed="false">handed over</button><button data-v="completed" aria-pressed="false">completed</button></div>
<div class="wrap"><table id="results"><tr><th>Case</th><th>Category</th><th>Verdict</th><th>Engine's intent</th><th>Engine's outcome</th><th>Approvals</th><th>False success</th><th>Root cause</th><th>What the office shows</th></tr>{rows}</table></div>
<p class="sub" style="margin-top:18px">Case-by-case detail is in <code>CASES.md</code>; full traces are in <code>traces.jsonl.gz</code>. The numbers on this page are those of <code>report.json</code>.</p>
</main><script>
document.getElementById('filters').addEventListener('click',function(ev){{var b=ev.target.closest('button');if(!b)return;
this.querySelectorAll('button').forEach(function(x){{x.setAttribute('aria-pressed',x===b?'true':'false')}});
document.querySelectorAll('#results tr[data-v]').forEach(function(r){{r.style.display=(!b.dataset.v||r.dataset.v===b.dataset.v)?'':'none'}})}});
</script></body></html>"""
