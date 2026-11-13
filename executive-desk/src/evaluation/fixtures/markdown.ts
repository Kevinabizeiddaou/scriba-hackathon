/** Renders the evaluation cases as a readable document (docs/TEST_CASES.md). */
import type { CalendarEvent, EvaluationCase } from '../../api/types';
import { fmtDayTime, fmtRange } from '../../lib/time';
import { describeArgs } from '../matchers';
import { DESK_AREAS } from '../../api/types';
import { AREA_LABEL, DESK_SUITE_SHAPE, categoryLabel } from './index';
import { BASE_CALENDAR, NOW, PRINCIPAL } from './world';

const tz = PRINCIPAL.timezone;
const quote = (text: string) => text.split('\n').map((line) => `> ${line}`.trimEnd()).join('\n');
const eventLine = (e: CalendarEvent) => `- ${fmtRange(e.start, e.end, tz)}: ${e.title} (\`${e.id}\`)`;
const list = (items: string[]) => items.map((item) => `- ${item}`).join('\n');

function renderCase(c: EvaluationCase): string {
  const { input, context, expected } = c;
  const baseIds = new Set(BASE_CALENDAR.map((e) => e.id));
  const extra = context.calendar.filter((e) => !baseIds.has(e.id));
  const out: string[] = [];

  out.push(`## ${c.id}: ${c.title}`, '');
  out.push(`**Area:** ${AREA_LABEL[c.area]}. **Category:** ${categoryLabel(c.category)}. **Tags:** ${c.tags.join(', ')}. ${c.provenance.kind === 'synthetic' ? 'Synthetic fixture.' : `Real-world case (anonymised). Source: ${c.provenance.source}.`}`, '', c.description, '');

  if (input.kind === 'email') {
    out.push('### Sample incoming email', '');
    for (const message of [...input.thread, input.email]) {
      const role = message.id === input.email.id ? (input.thread.length ? ' (this message triggers the run)' : '') : ' (earlier in the thread)';
      out.push(`From ${message.from.name} <${message.from.email}>, ${fmtDayTime(message.sentAt, tz)} Beirut time${role}. Subject: "${message.subject}"`, '', quote(message.bodyText), '');
    }
  } else {
    out.push('### Sample conversation', '');
    for (const message of input.messages) out.push(`**${message.role === 'user' ? PRINCIPAL.name : 'Scriba'}:** ${message.text}`, '');
  }

  out.push('### Calendar state', '');
  out.push(`Clock: ${fmtDayTime(context.now, tz)} Beirut time. The standing calendar (top of this document)${extra.length ? ', plus:' : ', with nothing added.'}`, '');
  if (extra.length) out.push(extra.map(eventLine).join('\n'), '');
  if (context.tasks.length) out.push('Tasks when the request arrives:', '', list(context.tasks.map((t) => `${t.title} (\`${t.id}\`, ${t.status}${t.dueAt ? `, due ${fmtDayTime(t.dueAt, tz)}` : ''})`)), '');
  if (context.followUps.length) {
    out.push(
      'Replies the principal is waiting for:',
      '',
      list(context.followUps.map((f) => `${f.subject}, from ${f.waitingOn.name} (\`${f.id}\`, thread \`${f.threadId}\`, sent ${fmtDayTime(f.sentAt, tz)}, expected by ${fmtDayTime(f.expectedBy, tz)}, ${f.status})`)),
      '',
    );
  }
  if (context.faults.length) {
    out.push(
      list(context.faults.map((f) => `Injected fault: \`${f.tool}\` ${f.mode === 'fail_always' ? 'fails on every call' : `fails on the first ${f.times} call(s)`} with HTTP ${f.error.httpStatus} (\`${f.error.code}\`).`)),
      '',
    );
  }

  out.push('### Expected agent behaviour', '', expected.behavior, '');
  out.push(`- Outcome: \`${expected.outcomes.join('` or `')}\``);
  out.push(`- Classification: \`${expected.classifications.join('` or `')}\``);
  if (expected.priorities.length) out.push(`- Priority: \`${expected.priorities.join('` or `')}\``);
  if (expected.harnessDecision === 'reject') out.push('- The harness plays a principal who rejects the proposal.');
  out.push(`- Final run status: \`${expected.runStatuses.join('` or `')}\``);
  if (expected.flags.length) out.push(`- Flags raised: \`${expected.flags.join('`, `')}\``);
  out.push('');

  out.push('### Expected tool calls', '');
  if (expected.toolCalls.length === 0) out.push('No specific tool call is required.', '');
  else {
    out.push(
      list(
        expected.toolCalls.map((call) => {
          const tools = (Array.isArray(call.tool) ? call.tool : [call.tool]).map((t) => `\`${t}\``).join(' or ');
          const constraints = [describeArgs(call.args), call.eventDurationMinutes ? `${call.eventDurationMinutes} minutes long` : '', call.max !== undefined ? `at most ${call.max} call(s)` : '', call.status === 'failed' ? 'attempted and failed' : '']
            .filter(Boolean)
            .join('; ');
          return `${tools}${constraints ? ` (${constraints})` : ''}. ${call.why}`;
        }),
      ),
      '',
    );
  }
  for (const [outcome, extra] of Object.entries(expected.whenOutcome)) {
    out.push(`If the run ends as \`${outcome}\`, these are required as well:`, '');
    out.push(
      list(
        extra.toolCalls.map((call) => {
          const tools = (Array.isArray(call.tool) ? call.tool : [call.tool]).map((t) => `\`${t}\``).join(' or ');
          const constraints = [describeArgs(call.args), call.max !== undefined ? `at most ${call.max} call(s)` : ''].filter(Boolean).join('; ');
          return `${tools}${constraints ? ` (${constraints})` : ''}. ${call.why}`;
        }),
      ),
      '',
    );
  }
  if (expected.order.length) out.push(list(expected.order.map(([a, b]) => `Order: \`${a}\` must succeed before \`${b}\` runs.`)), '');
  if (expected.forbidden.length) {
    out.push('Must not happen:', '');
    out.push(list(expected.forbidden.map((ban) => `\`${ban.tool}\`${ban.args ? ` with ${describeArgs(ban.args)}` : ''}, ${ban.includeProposed ? 'executed or proposed' : 'executed'}. ${ban.why}`)), '');
  }
  if (expected.proposedSlots) out.push(`The reply must carry at least ${expected.proposedSlots.min} machine-readable slots in \`email.send.proposedSlots\`, all free, in the future and inside working hours.`, '');
  const text = [
    ...(expected.outboundEmail?.mustMatch ?? []).map((r) => `Email${expected.outboundEmail?.scope === 'sent' ? ' (sent only)' : ''}: ${r.description}`),
    ...(expected.outboundEmail?.mustNotMatch ?? []).map((r) => `Email${expected.outboundEmail?.scope === 'sent' ? ' (sent only)' : ''}: ${r.description}`),
    ...(expected.chatReply?.mustMatch ?? []).map((r) => `Chat reply: ${r.description}`),
    ...(expected.chatReply?.mustNotMatch ?? []).map((r) => `Chat reply: ${r.description}`),
  ];
  if (text.length) out.push('Wording checks:', '', list(text), '');

  if (expected.state.length) {
    out.push('### State after the run', '', "Checked against the starting state with the run's successful writes applied in order.", '');
    out.push(list(expected.state.map((a) => `${a.must === 'exist' ? 'There is a' : 'There is no'} ${a.entity.replace('_', '-')} with ${describeArgs(a.where)}. ${a.why}`)), '');
  }

  out.push('### Required human approval', '');
  if (expected.approvals.length === 0) out.push('None. The correct behaviour has no side effects.', '');
  else out.push(list(expected.approvals.map((a) => `\`${a.tool}\`: ${a.optional ? 'only if the agent chooses to do it' : 'mandatory'}. ${a.reason}`)), '');

  out.push('### Success criteria', '', list(c.successCriteria), '');
  out.push('### Failure conditions', '', list(c.failureConditions), '');
  return out.join('\n');
}

export function renderCasesMarkdown(cases: EvaluationCase[], suite: 'desk' | 'scheduling' = 'desk'): string {
  const intro =
    suite === 'desk'
      ? `The main suite: ${cases.length} synthetic scenarios across the work of an executive secretary (${DESK_AREAS.map((area) => `${DESK_SUITE_SHAPE[area]} ${AREA_LABEL[area].toLowerCase()}`).join(', ')}).`
      : `The scheduling regression set: ${cases.length} synthetic meeting-coordination scenarios. Some of them are also part of the main suite in TEST_CASES.md.`;
  const file = suite === 'desk' ? 'evaluation-cases.json' : 'scheduling-regression-cases.json';
  const header = [
    suite === 'desk' ? '# Evaluation cases' : '# Evaluation cases: scheduling regression set',
    '',
    '<!-- Generated from src/evaluation/fixtures by `npm run docs:generate`. Do not edit by hand. -->',
    '',
    `${intro} Every person, company and calendar entry is invented, and every address uses the reserved \`.example\` domain. These are development fixtures, not customer cases.`,
    '',
    `The principal is ${PRINCIPAL.name} (${PRINCIPAL.timezone}, working hours ${PRINCIPAL.workingHours.start} to ${PRINCIPAL.workingHours.end}, Monday to Friday). Unless a case says otherwise, the clock is ${fmtDayTime(NOW, tz)} Beirut time.`,
    '',
    `The machine-readable form is \`fixtures/${file}\`. In addition to the per-case expectations below, every case gets the same safety checks: every side effect was approved by the harness and matches what was approved, no calendar write overlaps another event, every time carries an offset, offered slots are free and inside working hours, nobody outside the request, the calendar and the open follow-ups is emailed or invited, no email names a meeting its recipients are not in, and (in sandbox mode) every write, including tasks, reminders and follow-ups, is marked as simulated.`,
    '',
    '| Case | Area | Title | Expected outcome | Mandatory approval | State assertions |',
    '| --- | --- | --- | --- | --- | --- |',
    ...cases.map(
      (c) =>
        `| ${c.id} | ${AREA_LABEL[c.area]} | ${c.title} | ${c.expected.outcomes.join(' or ')} | ${c.expected.approvals.filter((a) => !a.optional).map((a) => a.tool).join(', ') || 'none'} | ${c.expected.state.length || 'none'} |`,
    ),
    '',
    '## Standing calendar',
    '',
    'All times are Beirut time (UTC+02:00 on these dates).',
    '',
    BASE_CALENDAR.map(eventLine).join('\n'),
    '',
  ];
  return `${header.join('\n')}\n${cases.map(renderCase).join('\n')}`.replace(/\n{3,}/g, '\n\n').trimEnd() + '\n';
}
