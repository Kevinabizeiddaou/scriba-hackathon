import clsx from 'clsx';
import { AlarmClock, BellOff, Check, ListTodo, MailQuestion, Reply, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { getApi, getWorkspace } from '../harness';
import type { FollowUp, Reminder, WorkTask } from '../harness/workspace';
import { WorkspaceUnavailable } from '../harness/workspace';
import { Button, EmptyState, ErrorNote, PageHeader, Pill, SkeletonRows } from '../components/ui';
import { WorkspaceState, dueLabel, nowMs } from '../components/workspace';
import { PRIORITY, type Tone } from '../lib/labels';
import { hrefFor, navigate } from '../lib/router';
import { fmtDayTime } from '../lib/time';
import { useWorkspace } from '../lib/useResource';
import { LiveFollowUps, tracksFollowUps } from '../live/LiveFollowUps';
import { useLiveSession } from '../live/session';

type Tab = 'tasks' | 'reminders' | 'followups';
const TABS: { id: Tab; label: string }[] = [
  { id: 'tasks', label: 'Tasks' },
  { id: 'reminders', label: 'Reminders' },
  { id: 'followups', label: 'Follow-ups' },
];

const FOLLOW_UP: Record<FollowUp['status'], { label: string; tone: Tone }> = {
  waiting: { label: 'Waiting for reply', tone: 'info' },
  overdue: { label: 'Overdue', tone: 'danger' },
  replied: { label: 'Replied', tone: 'ok' },
  closed: { label: 'Closed', tone: 'neutral' },
};

function Due({ iso, done = false }: { iso: string | null; done?: boolean }) {
  const tz = getApi().info.principal.timezone;
  if (!iso) return <span className="text-[12px] text-mute">No deadline</span>;
  if (done) return <span className="text-[12px] tabular-nums text-mute">Was due {fmtDayTime(iso, tz)}</span>;
  const due = dueLabel(iso, tz);
  return <span className={clsx('text-[12px] font-semibold tabular-nums', due.overdue ? 'text-danger' : due.today ? 'text-warn' : 'text-soft')}>{due.text}</span>;
}

function TaskRow({ task, onError }: { task: WorkTask; onError: (error: Error) => void }) {
  const done = task.status === 'done';
  const toggle = () => getWorkspace().setTaskStatus(task.id, done ? 'open' : 'done').catch(onError);
  return (
    <li className="flex items-start gap-3 rounded-xl border border-line bg-white/[0.02] px-3.5 py-3">
      <button
        type="button"
        role="checkbox"
        aria-checked={done}
        aria-label={`${done ? 'Reopen' : 'Complete'}: ${task.title}`}
        onClick={toggle}
        className={clsx('hit mt-0.5 flex h-5 w-5 shrink-0 cursor-pointer items-center justify-center rounded-md border transition-colors duration-150', done ? 'border-ok/60 bg-ok/20 text-ok' : 'border-line-strong text-transparent hover:border-accent')}
      >
        <Check aria-hidden className="h-3.5 w-3.5" strokeWidth={3} />
      </button>
      <div className="min-w-0 flex-1">
        <p className={clsx('text-[13.5px] font-semibold', done ? 'text-mute line-through decoration-white/25' : 'text-ink')}>{task.title}</p>
        {task.detail && <p className="mt-0.5 text-[12.5px] text-soft">{task.detail}</p>}
        <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1">
          <Due iso={task.dueAt} done={done} />
          {!done && (task.priority === 'urgent' || task.priority === 'high') && (
            <Pill tone={PRIORITY[task.priority].tone} icon={null}>
              {PRIORITY[task.priority].label}
            </Pill>
          )}
          <span className="text-[12px] text-mute">{task.origin === 'extracted' ? 'Found in an email' : 'Added by you'}</span>
          {task.sourceEmailId && (
            <a href={hrefFor('inbox', task.sourceEmailId)} className="tap inline-flex items-center text-[12px] font-medium text-accent hover:underline">
              Open the email
            </a>
          )}
        </p>
      </div>
    </li>
  );
}

function Group({ title, count, children }: { title: string; count: number; children: React.ReactNode }) {
  if (count === 0) return null;
  return (
    <section aria-label={title}>
      <h2 className="eyebrow mb-2">
        {title} <span className="tabular-nums">({count})</span>
      </h2>
      <ul className="space-y-2">{children}</ul>
    </section>
  );
}

function ReminderRow({ reminder, onError }: { reminder: Reminder; onError: (error: Error) => void }) {
  const active = reminder.status === 'scheduled';
  const set = (status: Reminder['status']) => getWorkspace().setReminderStatus(reminder.id, status).catch(onError);
  return (
    <li className="flex flex-wrap items-center gap-3 rounded-xl border border-line bg-white/[0.02] px-3.5 py-3">
      <AlarmClock aria-hidden className={clsx('h-4 w-4 shrink-0', active ? 'text-accent' : 'text-mute')} />
      <div className="min-w-0 flex-1">
        <p className={clsx('text-[13.5px] font-semibold', active ? 'text-ink' : 'text-mute line-through decoration-white/25')}>{reminder.text}</p>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-3">
          <Due iso={reminder.remindAt} done={!active} />
          {reminder.sourceEmailId && (
            <a href={hrefFor('inbox', reminder.sourceEmailId)} className="tap inline-flex items-center text-[12px] font-medium text-accent hover:underline">
              Open the email
            </a>
          )}
        </p>
      </div>
      {active ? (
        <div className="flex gap-2">
          <Button variant="ghost" icon={BellOff} className="h-8 px-2.5" onClick={() => set('dismissed')}>
            Dismiss
          </Button>
          <Button variant="secondary" icon={Check} className="h-8 px-2.5" onClick={() => set('done')}>
            Done
          </Button>
        </div>
      ) : (
        <Pill tone="neutral" icon={null}>
          {reminder.status === 'done' ? 'Done' : 'Dismissed'}
        </Pill>
      )}
    </li>
  );
}

function FollowUpRow({ followUp, onError }: { followUp: FollowUp; onError: (error: Error) => void }) {
  const tz = getApi().info.principal.timezone;
  const [busy, setBusy] = useState(false);
  const status = FOLLOW_UP[followUp.status];
  const open = followUp.status === 'waiting' || followUp.status === 'overdue';
  async function nudge() {
    setBusy(true);
    try {
      await getWorkspace().draftNudge(followUp.id);
    } catch (cause) {
      onError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(false);
    }
  }
  return (
    <li className={clsx('rounded-xl border bg-white/[0.02] px-3.5 py-3', followUp.status === 'overdue' ? 'border-danger/35' : 'border-line')}>
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
        <div className="min-w-0">
          <p className="text-[13.5px] font-semibold text-ink">{followUp.subject}</p>
          <p className="text-[12.5px] text-soft">
            {followUp.status === 'replied' ? 'Answered by' : 'Waiting on'} {followUp.waitingOn.name} <span className="text-mute">&lt;{followUp.waitingOn.email}&gt;</span>
          </p>
        </div>
        <Pill tone={status.tone}>{status.label}</Pill>
      </div>
      <dl className="mt-2 flex flex-wrap gap-x-6 gap-y-1 text-[12px]">
        <div className="flex gap-1.5">
          <dt className="text-mute">Sent</dt>
          <dd className="tabular-nums text-soft">{fmtDayTime(followUp.sentAt, tz)}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt className="text-mute">Answer expected</dt>
          <dd className={clsx('tabular-nums', followUp.status === 'overdue' ? 'font-semibold text-danger' : 'text-soft')}>{fmtDayTime(followUp.expectedBy, tz)}</dd>
        </div>
        <div className="flex gap-1.5">
          <dt className="text-mute">Reminders sent</dt>
          <dd className="tabular-nums text-soft">{followUp.nudgesSent}</dd>
        </div>
      </dl>
      {followUp.note && <p className="mt-2 text-[12.5px] text-soft">{followUp.note}</p>}
      <div className="mt-2.5 flex flex-wrap items-center gap-3">
        {followUp.nudgeApprovalId ? (
          <a href={hrefFor('approvals', followUp.nudgeApprovalId)} className="btn btn-primary h-8">
            <ShieldCheck aria-hidden className="h-4 w-4" />
            Review the reminder
          </a>
        ) : (
          open &&
          followUp.nudgesSent === 0 && (
            <Button variant={followUp.status === 'overdue' ? 'primary' : 'secondary'} icon={Reply} busy={busy} className="h-8" onClick={nudge}>
              Draft a reminder
            </Button>
          )
        )}
        {followUp.emailId && (
          <a href={hrefFor('inbox', followUp.emailId)} className="tap inline-flex items-center text-[12.5px] font-medium text-accent hover:underline">
            Open the thread
          </a>
        )}
      </div>
    </li>
  );
}

export function TasksPage({ tab: requested }: { tab: string | null }) {
  const tab: Tab = TABS.some((t) => t.id === requested) ? (requested as Tab) : 'tasks';
  const [error, setError] = useState<Error | null>(null);
  const data = useWorkspace(async (w) => {
    // Follow-up tracking may have no backend. That must not hide the tasks and reminders that do load.
    const [tasks, reminders, followUps] = await Promise.all([
      w.listTasks(),
      w.listReminders(),
      w.listFollowUps().catch((cause: unknown) => {
        if (cause instanceof WorkspaceUnavailable) return cause;
        throw cause;
      }),
    ]);
    return followUps instanceof WorkspaceUnavailable ? { tasks, reminders, followUps: [], followUpsUnavailable: followUps } : { tasks, reminders, followUps, followUpsUnavailable: null };
  }, []);

  const now = nowMs();
  const tz = getApi().info.principal.timezone;
  const tasks = data.data?.tasks ?? [];
  const open = tasks.filter((t) => t.status === 'open').sort((a, b) => Date.parse(a.dueAt ?? '9999') - Date.parse(b.dueAt ?? '9999'));
  const overdue = open.filter((t) => t.dueAt && Date.parse(t.dueAt) < now);
  const today = open.filter((t) => t.dueAt && Date.parse(t.dueAt) >= now && dueLabel(t.dueAt, tz).today);
  const later = open.filter((t) => !overdue.includes(t) && !today.includes(t));
  const done = tasks.filter((t) => t.status === 'done');
  const reminders = [...(data.data?.reminders ?? [])].sort((a, b) => Number(b.status === 'scheduled') - Number(a.status === 'scheduled') || Date.parse(a.remindAt) - Date.parse(b.remindAt));
  const rank: Record<FollowUp['status'], number> = { overdue: 0, waiting: 1, replied: 2, closed: 3 };
  const followUps = [...(data.data?.followUps ?? [])].sort((a, b) => rank[a.status] - rank[b.status]);
  // On a backend that tracks awaited replies (overlay 0.3) the follow-ups come from it, not from the workspace model.
  const session = useLiveSession();
  const liveFollowUps = tracksFollowUps(session);
  const [liveOpen, setLiveOpen] = useState<number | null>(null);
  const counts: Record<Tab, number | null> = { tasks: open.length, reminders: reminders.filter((r) => r.status === 'scheduled').length, followups: liveFollowUps ? liveOpen : followUps.filter((f) => f.status === 'waiting' || f.status === 'overdue').length };

  return (
    <div>
      <PageHeader title="Tasks and follow-ups" subtitle="What the secretary found for you to do, what it will remind you of, and whose reply you are still waiting for." />
      <div className="px-4 pb-12 sm:px-6 lg:px-8">
        <div role="tablist" aria-label="Tasks and follow-ups" className="mb-4 inline-flex max-w-full overflow-x-auto rounded-full border border-line bg-sunken/60 p-1">
          {TABS.map(({ id, label }) => (
            <button
              key={id}
              id={`tab-${id}`}
              role="tab"
              type="button"
              aria-selected={tab === id}
              aria-controls="tasks-panel"
              onClick={() => navigate('tasks', id)}
              className={clsx('tap inline-flex h-8 shrink-0 cursor-pointer items-center gap-2 rounded-full px-3.5 text-[13px] font-semibold transition-colors duration-150', tab === id ? 'bg-brand-500/50 text-ink' : 'text-soft hover:text-ink')}
            >
              {label}
              <span className={clsx('tabular-nums', tab === id ? 'text-accent' : 'text-mute')}>{counts[id] ?? ''}</span>
            </button>
          ))}
        </div>

        <div id="tasks-panel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="max-w-3xl space-y-5">
          {error && <ErrorNote error={error} />}
          {session?.mode.kind === 'sandbox' && tab !== 'followups' && (
            <p role="status" className="rounded-xl border border-warn/30 bg-warn/[0.07] px-3.5 py-2.5 text-[13px] text-warn" data-testid="tasks-sandbox">
              {tab === 'tasks'
                ? 'Sandbox tasks: the open tasks of the sandbox world, including any the secretary recorded there after your approval. Scriba\'s own task list is not shown. A sandbox task is completed through a proposal in the work queue, not from this list.'
                : 'Sandbox reminders: this backend has no route that lists the sandbox world\'s reminders, so none are listed here. A reminder the secretary set in the sandbox is on its run in the work queue and in the activity record.'}
            </p>
          )}
          <WorkspaceState error={data.error} onRetry={data.reload}>
            {data.loading ? (
              <SkeletonRows rows={4} />
            ) : tab === 'tasks' ? (
              tasks.length === 0 ? (
                <EmptyState icon={ListTodo} title="No tasks">
                  When an email asks you to do something, the secretary records it here with its deadline.
                </EmptyState>
              ) : (
                <>
                  <Group title="Overdue" count={overdue.length}>
                    {overdue.map((t) => <TaskRow key={t.id} task={t} onError={setError} />)}
                  </Group>
                  <Group title="Due today" count={today.length}>
                    {today.map((t) => <TaskRow key={t.id} task={t} onError={setError} />)}
                  </Group>
                  <Group title="Upcoming" count={later.length}>
                    {later.map((t) => <TaskRow key={t.id} task={t} onError={setError} />)}
                  </Group>
                  <Group title="Done" count={done.length}>
                    {done.map((t) => <TaskRow key={t.id} task={t} onError={setError} />)}
                  </Group>
                </>
              )
            ) : tab === 'reminders' ? (
              reminders.length === 0 ? (
                <EmptyState icon={AlarmClock} title="No reminders">
                  Ask in chat, for example "remind me on Thursday at 9 to call Karim".
                </EmptyState>
              ) : (
                <ul className="space-y-2" aria-label="Reminders">
                  {reminders.map((r) => <ReminderRow key={r.id} reminder={r} onError={setError} />)}
                </ul>
              )
            ) : liveFollowUps ? (
              <LiveFollowUps onCount={setLiveOpen} />
            ) : data.data?.followUpsUnavailable ? (
              <EmptyState icon={MailQuestion} title="Follow-up tracking is not available yet">
                {data.data.followUpsUnavailable.message}
              </EmptyState>
            ) : followUps.length === 0 ? (
              <EmptyState icon={MailQuestion} title="Nobody owes you a reply">
                When you are waiting for an answer to something you sent, it is tracked here.
              </EmptyState>
            ) : (
              <ul className="space-y-2" aria-label="Follow-ups">
                {followUps.map((f) => <FollowUpRow key={f.id} followUp={f} onError={setError} />)}
              </ul>
            )}
          </WorkspaceState>
        </div>
      </div>
    </div>
  );
}
