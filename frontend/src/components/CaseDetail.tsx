import clsx from 'clsx';
import { Check, X } from 'lucide-react';
import type { ReactNode } from 'react';
import type { EvaluationCase, EvaluationResult } from '../harness/types';
import { describeArgs } from '../evaluation/matchers';
import { totalTokens } from '../evaluation/pricing';
import { usd } from '../lib/labels';
import { fmtDayTime, fmtDuration, fmtRange } from '../lib/time';
import { ActionTimeline } from './ActionTimeline';

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="min-w-0">
      <h4 className="eyebrow mb-2">{title}</h4>
      {children}
    </section>
  );
}

function Bullets({ items }: { items: string[] }) {
  return (
    <ul className="list-disc space-y-1 pl-4 text-[13px] text-soft marker:text-mute">
      {items.map((item) => (
        <li key={item}>{item}</li>
      ))}
    </ul>
  );
}

function toolName(tool: string | string[]): string {
  return Array.isArray(tool) ? tool.join(' or ') : tool;
}

/** The written definition of a case: what arrives, the calendar at that moment, and what a good agent does. */
export function CaseSpecification({ testCase }: { testCase: EvaluationCase }) {
  const { input, context, expected } = testCase;
  const tz = context.principal.timezone;
  return (
    <div className="grid gap-x-8 gap-y-5 lg:grid-cols-2">
      <div className="space-y-5">
        <Block title={input.kind === 'email' ? 'Incoming email (synthetic)' : 'Chat message (synthetic)'}>
          {input.kind === 'email' ? (
            <div className="space-y-2">
              {[...input.thread, input.email].map((message, i, all) => (
                <div key={message.id} className="rounded-lg border border-line bg-sunken/70 px-3 py-2.5">
                  <p className="text-[12px] text-mute">
                    <span className="font-semibold text-soft">{message.from.name}</span> &lt;{message.from.email}&gt; · {fmtDayTime(message.sentAt, tz)}
                    {all.length > 1 && i === all.length - 1 && <span className="ml-1 text-accent">(triggers the run)</span>}
                  </p>
                  <p className="mt-0.5 text-[13px] font-semibold text-ink">{message.subject}</p>
                  <p className="mt-1 whitespace-pre-wrap text-[13px] leading-5 text-soft">{message.bodyText}</p>
                </div>
              ))}
            </div>
          ) : (
            <div className="space-y-2">
              {input.messages.map((message, i) => (
                <p key={i} className="rounded-lg border border-line bg-sunken/70 px-3 py-2.5 text-[13px] text-ink">
                  <span className="mr-2 text-[12px] font-semibold text-mute">{message.role === 'user' ? context.principal.name : 'Scriba'}</span>
                  {message.text}
                </p>
              ))}
            </div>
          )}
        </Block>

        <Block title={`Calendar state at ${fmtDayTime(context.now, tz)}`}>
          <ul className="divide-y divide-line rounded-lg border border-line bg-sunken/70">
            {context.calendar.map((event) => (
              <li key={event.id} className="flex flex-wrap items-baseline gap-x-3 px-3 py-1.5 text-[12.5px]">
                <span className="w-[178px] shrink-0 tabular-nums text-mute">{fmtRange(event.start, event.end, tz)}</span>
                <span className="min-w-0 flex-1 text-ink">{event.title}</span>
                <span className="font-mono text-xs text-mute">{event.id}</span>
              </li>
            ))}
          </ul>
          {context.tasks.length > 0 && (
            <ul aria-label="Tasks when the request arrives" className="mt-2 divide-y divide-line rounded-lg border border-line bg-sunken/70">
              {context.tasks.map((task) => (
                <li key={task.id} className="flex flex-wrap items-baseline gap-x-3 px-3 py-1.5 text-[12.5px]">
                  <span className="w-[178px] shrink-0 text-mute">Task, {task.status}{task.dueAt ? `, due ${fmtDayTime(task.dueAt, tz)}` : ''}</span>
                  <span className="min-w-0 flex-1 text-ink">{task.title}</span>
                  <span className="font-mono text-xs text-mute">{task.id}</span>
                </li>
              ))}
            </ul>
          )}
          {context.followUps.length > 0 && (
            <ul aria-label="Replies awaited when the request arrives" className="mt-2 divide-y divide-line rounded-lg border border-line bg-sunken/70">
              {context.followUps.map((followUp) => (
                <li key={followUp.id} className="flex flex-wrap items-baseline gap-x-3 px-3 py-1.5 text-[12.5px]">
                  <span className="w-[178px] shrink-0 text-mute">Awaited by {fmtDayTime(followUp.expectedBy, tz)}</span>
                  <span className="min-w-0 flex-1 text-ink">
                    {followUp.subject}, from {followUp.waitingOn.name}
                  </span>
                  <span className="font-mono text-xs text-mute">{followUp.id}</span>
                </li>
              ))}
            </ul>
          )}
          {context.faults.length > 0 && (
            <p className="mt-2 rounded-lg border border-warn/25 bg-warn/[0.07] px-3 py-2 text-[12.5px] text-warn">
              Injected fault:{' '}
              {context.faults.map((f) => `${f.tool} ${f.mode === 'fail_always' ? 'always fails' : `fails ${f.times} time(s)`} with HTTP ${f.error.httpStatus}`).join('; ')}
            </p>
          )}
        </Block>
      </div>

      <div className="space-y-5">
        <Block title="Expected agent behaviour">
          <p className="text-[13.5px] leading-[21px] text-ink">{expected.behavior}</p>
          <dl className="mt-2.5 space-y-1 text-[12.5px]">
            <div className="flex gap-2">
              <dt className="w-24 shrink-0 text-mute">Outcome</dt>
              <dd className="font-mono text-soft">{expected.outcomes.join(' or ')}</dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-24 shrink-0 text-mute">Classification</dt>
              <dd className="font-mono text-soft">{expected.classifications.join(' or ')}</dd>
            </div>
            {expected.priorities.length > 0 && (
              <div className="flex gap-2">
                <dt className="w-24 shrink-0 text-mute">Priority</dt>
                <dd className="font-mono text-soft">{expected.priorities.join(' or ')}</dd>
              </div>
            )}
            {expected.harnessDecision === 'reject' && (
              <div className="flex gap-2">
                <dt className="w-24 shrink-0 text-mute">Human</dt>
                <dd className="text-soft">The harness rejects the proposal.</dd>
              </div>
            )}
            {expected.flags.length > 0 && (
              <div className="flex gap-2">
                <dt className="w-24 shrink-0 text-mute">Flags</dt>
                <dd className="font-mono text-soft">{expected.flags.join(', ')}</dd>
              </div>
            )}
          </dl>
        </Block>

        <Block title="Expected tool calls">
          {expected.toolCalls.length > 0 ? (
            <ul className="space-y-1.5">
              {expected.toolCalls.map((call, i) => (
                <li key={i} className="text-[13px]">
                  <span className="font-mono text-[12px] text-accent">{toolName(call.tool)}</span>
                  {call.status === 'failed' && <span className="text-mute"> (attempted, fails)</span>}
                  <span className="block text-soft">{call.why}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[13px] text-mute">No specific tool call is required.</p>
          )}
          {expected.forbidden.length > 0 && (
            <ul className="mt-2.5 space-y-1.5">
              {expected.forbidden.map((ban, i) => (
                <li key={i} className="text-[13px]">
                  <span className="font-mono text-[12px] text-danger">must not: {ban.tool}</span>
                  <span className="text-mute">{ban.includeProposed ? ' (not even as a proposal)' : ' (must not execute)'}</span>
                  <span className="block text-soft">{ban.why}</span>
                </li>
              ))}
            </ul>
          )}
        </Block>

        {expected.state.length > 0 && (
          <Block title="State after the run">
            <ul className="space-y-1.5">
              {expected.state.map((assertion, i) => (
                <li key={i} className="text-[13px]">
                  <span className={clsx('font-mono text-[12px]', assertion.must === 'exist' ? 'text-ok' : 'text-danger')}>
                    {assertion.must === 'exist' ? 'must exist' : 'must not exist'}: {assertion.entity.replace('_', '-')}
                  </span>
                  <span className="block text-soft">{assertion.why}</span>
                  <span className="block font-mono text-xs text-mute">{describeArgs(assertion.where)}</span>
                </li>
              ))}
            </ul>
          </Block>
        )}

        <Block title="Required human approval">
          {expected.approvals.length > 0 ? (
            <ul className="space-y-1.5">
              {expected.approvals.map((approval) => (
                <li key={approval.tool} className="text-[13px]">
                  <span className="font-mono text-[12px] text-warn">{approval.tool}</span>
                  <span className="text-mute">{approval.optional ? ' (only if the agent chooses to do it)' : ' (mandatory)'}</span>
                  <span className="block text-soft">{approval.reason}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[13px] text-mute">None. The correct behaviour here has no side effects.</p>
          )}
        </Block>

        <Block title="Success criteria">
          <Bullets items={testCase.successCriteria} />
        </Block>
        <Block title="Failure conditions">
          <Bullets items={testCase.failureConditions} />
        </Block>
      </div>
    </div>
  );
}

/** Expected versus actual for one executed case, plus its trace. */
export function CaseResult({ result, timeZone }: { result: EvaluationResult; timeZone: string }) {
  if (result.verdict === 'skipped') {
    return <p className="text-[13px] text-soft">Skipped: {result.skipReason ?? 'not executed'}.</p>;
  }
  const failed = result.checks.filter((c) => !c.passed);
  return (
    <div className="space-y-5">
      <div className="grid gap-x-8 gap-y-3 text-[13px] sm:grid-cols-2 xl:grid-cols-4">
        <div>
          <p className="eyebrow mb-1">Checks</p>
          <p className="text-ink">{result.checks.length > 0 ? `${result.checks.length - failed.length} of ${result.checks.length} passed` : 'Not scored'}</p>
        </div>
        <div>
          <p className="eyebrow mb-1">Human involvement</p>
          <p className="text-ink">
            {result.human.mandatoryApprovals} mandatory approval{result.human.mandatoryApprovals === 1 ? '' : 's'}
            {result.human.unexpectedApprovals > 0 && `, ${result.human.unexpectedApprovals} unexpected`}
          </p>
          <p className={result.human.rescued ? 'font-semibold text-warn' : 'text-mute'}>{result.human.rescued ? 'Rescued by a person' : 'No rescue'}</p>
        </div>
        <div>
          <p className="eyebrow mb-1">Duration</p>
          {result.dataSource === 'live' ? (
            <>
              <p className="tabular-nums text-ink">{fmtDuration(result.timing.wallClockMs)} measured</p>
              <p className="tabular-nums text-mute">{result.timing.agentReportedMs !== null ? `${fmtDuration(result.timing.agentReportedMs)} reported by the agent` : 'agent reported none'}</p>
            </>
          ) : (
            <p className="text-mute">Not measured: a scripted run does no real work.</p>
          )}
        </div>
        <div>
          <p className="eyebrow mb-1">Tokens and cost</p>
          {result.usage ? (
            <>
              <p className="tabular-nums text-ink">
                {totalTokens(result.usage).input} in, {totalTokens(result.usage).output} out
              </p>
              <p className="tabular-nums text-mute">
                {result.usage.models.map((m) => `${m.model} x${m.calls}`).join(', ') || 'no model named'} ·{' '}
                {result.estimatedCostUsd !== null ? `${usd(result.estimatedCostUsd)} (${result.costSource === 'backend' ? 'from backend' : 'from price table'})` : 'no price configured'}
              </p>
            </>
          ) : (
            <p className="text-mute">Not reported</p>
          )}
        </div>
      </div>

      {result.errors.length > 0 && (
        <Block title="API and model errors">
          <ul className="space-y-1">
            {result.errors.map((error, i) => (
              <li key={i} className="rounded-lg border border-warn/25 bg-warn/[0.07] px-3 py-1.5 text-[12.5px] text-warn">
                <span className="font-mono text-xs">
                  {error.source}/{error.code}
                </span>{' '}
                {error.message}
              </li>
            ))}
          </ul>
        </Block>
      )}

      {result.checks.length > 0 && (
        <Block title="Expected versus actual">
          <div className="relative overflow-x-auto rounded-lg border border-line">
            <table className="w-full min-w-[640px] text-left text-[12.5px]">
              <thead className="bg-white/[0.03] text-mute">
                <tr>
                  <th scope="col" className="w-20 px-3 py-2 font-semibold">Result</th>
                  <th scope="col" className="px-3 py-2 font-semibold">Check</th>
                  <th scope="col" className="px-3 py-2 font-semibold">Expected</th>
                  <th scope="col" className="px-3 py-2 font-semibold">Actual</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {result.checks.map((c) => (
                  <tr key={c.id} className={c.passed ? undefined : 'bg-danger/[0.06]'}>
                    <td className="px-3 py-2 align-top">
                      <span className={c.passed ? 'inline-flex items-center gap-1 font-semibold text-ok' : 'inline-flex items-center gap-1 font-semibold text-danger'}>
                        {c.passed ? <Check aria-hidden className="h-3.5 w-3.5" strokeWidth={3} /> : <X aria-hidden className="h-3.5 w-3.5" strokeWidth={3} />}
                        {c.passed ? 'Pass' : 'Fail'}
                      </span>
                    </td>
                    <td className="px-3 py-2 align-top text-ink">{c.label}</td>
                    <td className="break-words px-3 py-2 align-top text-soft">{c.expected}</td>
                    <td className={c.passed ? 'break-words px-3 py-2 align-top text-soft' : 'break-words px-3 py-2 align-top font-medium text-danger'}>{c.actual}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Block>
      )}

      {result.run && (
        <Block title="Execution trace">
          {result.run.summary && <p className="mb-3 text-[13px] text-soft">{result.run.summary}</p>}
          <ActionTimeline actions={result.run.actions} timeZone={timeZone} detailed />
        </Block>
      )}
    </div>
  );
}
