import clsx from 'clsx';
import { ArrowLeft, CalendarDays, CheckSquare, Inbox, Info, ListChecks, ListTodo, Reply, RotateCcw, Send, ShieldCheck, Sparkles, type LucideIcon } from 'lucide-react';
import { useState } from 'react';
import { getApi, getWorkspace } from '../harness';
import type { EmailCategory, EmailWorkStatus, InboxEmail, MailProvider } from '../harness/workspace';
import { RequestDetail } from '../components/RequestDetail';
import { Button, EmptyState, ErrorNote, PageHeader, Pill, SkeletonRows } from '../components/ui';
import { EMAIL_CATEGORY, EMAIL_STATUS, SourceBadge, WorkspaceState } from '../components/workspace';
import { FLAG, PRIORITY } from '../lib/labels';
import { hrefFor } from '../lib/router';
import { fmtDayTime } from '../lib/time';
import { LiveEmailDetail } from '../live/LiveEmailDetail';
import { sourceProblems } from '../live/LiveOverviewPage';
import { useLiveSession } from '../live/session';
import { useResource, useWorkspace } from '../lib/useResource';

/** Each kind of mail has its own icon, so a meeting request, an action and a reply can be told apart at a glance. */
const CATEGORY_ICON: Record<EmailCategory, LucideIcon> = { meeting: CalendarDays, action_required: ListTodo, reply_needed: Reply, follow_up: RotateCcw, fyi: Info, low_priority: Info };

interface Filter {
  id: string;
  label: string;
  statuses: EmailWorkStatus[] | null;
  meetings?: boolean;
  categories?: EmailCategory[];
}

/** Live mail has a triage category but no work status, so it is filtered by what each message needs. */
const LIVE_FILTERS: Filter[] = [
  { id: 'all', label: 'All', statuses: null },
  { id: 'attention', label: 'Needs action', statuses: null, categories: ['meeting', 'reply_needed', 'action_required'] },
  { id: 'meetings', label: 'Meetings', statuses: null, meetings: true },
  { id: 'replies', label: 'Replies', statuses: null, categories: ['reply_needed'] },
  { id: 'actions', label: 'Action items', statuses: null, categories: ['action_required'] },
  { id: 'fyi', label: 'For information', statuses: null, categories: ['fyi', 'low_priority'] },
];

const FILTERS: Filter[] = [
  { id: 'all', label: 'All', statuses: null },
  { id: 'attention', label: 'Needs you', statuses: ['needs_you', 'needs_approval'] },
  { id: 'new', label: 'New', statuses: ['new'] },
  { id: 'open', label: 'In progress', statuses: ['in_progress', 'waiting'] },
  { id: 'meetings', label: 'Meetings', statuses: null, meetings: true },
  { id: 'done', label: 'Done', statuses: ['done'] },
];

const DRAFT_STATE = {
  drafted: { label: 'Draft, not sent', tone: 'neutral' },
  awaiting_approval: { label: 'Waiting for your approval', tone: 'warn' },
  sent: { label: 'Sent', tone: 'ok' },
  rejected: { label: 'Rejected, not sent', tone: 'neutral' },
} as const;

function EmailDetail({ email }: { email: InboxEmail }) {
  const { principal, dataSource } = getApi().info;
  const tz = principal.timezone;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const request = useResource((api) => (email.requestId ? api.getRequest(email.requestId) : Promise.resolve(null)), [email.requestId]);
  const status = EMAIL_STATUS[email.status];

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await getWorkspace().submitDraft(email.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="space-y-4 p-4 sm:p-6" aria-label={`Email: ${email.subject}`}>
      <a href={hrefFor('inbox')} className="tap inline-flex items-center gap-1.5 text-[13px] font-medium text-accent hover:underline lg:hidden">
        <ArrowLeft aria-hidden className="h-4 w-4" />
        Inbox
      </a>

      <header>
        <h2 className="text-[19px] font-bold leading-7 text-ink">{email.subject}</h2>
        <p className="mt-0.5 text-[13px] text-soft">
          {email.from.name} <span className="text-mute">&lt;{email.from.email}&gt;</span>
        </p>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12px] text-mute">
          <span className="tabular-nums">Received {fmtDayTime(email.receivedAt, tz)}</span>
          <SourceBadge source={email.provider} />
          <span>{email.account}</span>
        </p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          <Pill tone={status.tone} spin={email.status === 'in_progress' && email.requestId !== null && request.data?.status === 'processing'}>
            {status.label}
          </Pill>
          <Pill tone={EMAIL_CATEGORY[email.category].tone} icon={null}>
            {EMAIL_CATEGORY[email.category].label}
          </Pill>
          <Pill tone={PRIORITY[email.priority].tone} icon={null}>
            {PRIORITY[email.priority].label} priority
          </Pill>
          {email.flags.map((flag) => (
            <Pill key={flag} tone={FLAG[flag].tone}>
              {FLAG[flag].label}
            </Pill>
          ))}
        </div>
      </header>

      <section className="card p-4" aria-label="Summary">
        <h3 className="eyebrow mb-2 flex items-center gap-1.5">
          <Sparkles aria-hidden className="h-3.5 w-3.5 text-accent" />
          Secretary's summary
        </h3>
        <p className="text-[13.5px] leading-[21px] text-ink">{email.summary}</p>
        {email.actionItems.length > 0 && (
          <>
            <h4 className="eyebrow mb-1.5 mt-3.5 flex items-center gap-1.5">
              <ListChecks aria-hidden className="h-3.5 w-3.5 text-accent" />
              Action items
            </h4>
            <ul className="space-y-1">
              {email.actionItems.map((item) => (
                <li key={item} className="flex gap-2 text-[13px] text-ink">
                  <CheckSquare aria-hidden className="mt-0.5 h-3.5 w-3.5 shrink-0 text-mute" />
                  {item}
                </li>
              ))}
            </ul>
          </>
        )}
        {email.taskIds.length > 0 && (
          <a href={hrefFor('tasks')} className="tap mt-3 inline-flex items-center text-[12.5px] font-medium text-accent hover:underline">
            {email.taskIds.length === 1 ? 'A task was recorded from this email' : `${email.taskIds.length} tasks were recorded from this email`}
          </a>
        )}
      </section>

      {email.draft && (
        <section className={clsx('card p-4', email.draft.state === 'awaiting_approval' && 'border-warn/25')} aria-label="Reply draft">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <h3 className="eyebrow">Reply draft</h3>
            <Pill tone={DRAFT_STATE[email.draft.state].tone}>{DRAFT_STATE[email.draft.state].label}</Pill>
          </div>
          <dl className="space-y-1 text-[13px]">
            <div className="flex gap-3">
              <dt className="w-14 shrink-0 text-mute">To</dt>
              <dd className="min-w-0 break-words text-ink">{email.draft.to.join(', ')}</dd>
            </div>
            <div className="flex gap-3">
              <dt className="w-14 shrink-0 text-mute">Subject</dt>
              <dd className="min-w-0 break-words text-ink">{email.draft.subject}</dd>
            </div>
          </dl>
          <p className="mt-2.5 whitespace-pre-wrap rounded-lg border border-line bg-bg/60 px-3 py-2.5 text-[13.5px] leading-[21px] text-ink">{email.draft.bodyText}</p>
          <p className="mt-2.5 text-[12.5px] text-soft">
            <span className="font-semibold text-ink">Why it reads this way: </span>
            {email.draft.rationale}
          </p>
          {error && (
            <div className="mt-3">
              <ErrorNote error={error} />
            </div>
          )}
          <div className="mt-3.5 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
            <p className="text-[12px] text-mute">{dataSource === 'simulated' ? 'Mock mode: nothing leaves this browser.' : 'Nothing is sent until you approve it.'}</p>
            {email.draft.state === 'drafted' && !email.requestId && (
              <Button variant="primary" icon={Send} busy={busy} onClick={submit}>
                Send for approval
              </Button>
            )}
            {email.draft.approvalId && email.draft.state !== 'drafted' && (
              <a href={hrefFor('approvals', email.draft.approvalId)} className={clsx('btn', email.draft.state === 'awaiting_approval' ? 'btn-primary' : 'btn-secondary')}>
                <ShieldCheck aria-hidden className="h-4 w-4" />
                {email.draft.state === 'awaiting_approval' ? 'Review approval' : 'Open in approval center'}
              </a>
            )}
          </div>
        </section>
      )}

      <section className="card p-4" aria-label="Thread">
        <h3 className="eyebrow mb-3">
          Thread · {email.thread.length} {email.thread.length === 1 ? 'message' : 'messages'}
        </h3>
        <ol className="space-y-3">
          {email.thread.map((message) => (
            <li key={message.id} className={clsx('rounded-xl border px-3.5 py-3', message.outbound ? 'ml-6 border-brand-500/40 bg-brand-500/[0.12]' : 'mr-6 border-line bg-white/[0.025]')}>
              <p className="flex flex-wrap items-baseline justify-between gap-x-3 text-[12px]">
                <span className="font-semibold text-ink">
                  {message.from.name}
                  {message.outbound && <span className="ml-1.5 font-normal text-mute">(sent from your mailbox)</span>}
                </span>
                <span className="tabular-nums text-mute">{fmtDayTime(message.sentAt, tz)}</span>
              </p>
              <p className="mt-1.5 whitespace-pre-wrap text-[13.5px] leading-[21px] text-ink">{message.bodyText}</p>
            </li>
          ))}
        </ol>
      </section>

      {email.requestId && request.data && <RequestDetail request={request.data} />}
    </article>
  );
}

export function InboxPage({ emailId }: { emailId: string | null }) {
  const [filter, setFilter] = useState('all');
  const [provider, setProvider] = useState<MailProvider | 'all'>('all');
  const emails = useWorkspace((workspace) => workspace.listEmails(), []);
  const tz = getApi().info.principal.timezone;
  const session = useLiveSession();
  const live = session !== null;
  const filters = live ? LIVE_FILTERS : FILTERS;
  // Which mailbox is missing from the list, when one could not be read. Read after the load that filled it.
  const missing = session && emails.data ? sourceProblems(session.workspace.lastInbox?.sources ?? []) : [];

  const all = emails.data ?? [];
  const fromProvider = provider === 'all' ? all : all.filter((e) => e.provider === provider);
  const matches = (f: Filter, e: InboxEmail) => (f.meetings ? e.category === 'meeting' : f.categories ? f.categories.includes(e.category) : !f.statuses || f.statuses.includes(e.status));
  const active = filters.find((f) => f.id === filter) ?? filters[0];
  const visible = fromProvider.filter((e) => matches(active, e));
  const selected = all.find((e) => e.id === emailId) ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className={clsx(selected && 'hidden lg:block')}>
        <PageHeader title="Inbox" subtitle={live ? 'Gmail and Outlook in one place, newest first, each with what it needs next.' : 'Gmail and Outlook in one place, with what each message needs and what the secretary has done about it.'} />
      </div>

      <WorkspaceState error={emails.error} onRetry={emails.reload}>
        <div className="flex min-h-0 flex-1 border-t border-line">
          <section aria-label="Messages" className={clsx('flex w-full min-w-0 flex-col lg:w-[410px] lg:shrink-0 lg:border-r lg:border-line', selected && 'hidden lg:flex')}>
            <div className="border-b border-line px-3 py-2.5">
              <div role="group" aria-label="Filter by status" className="flex gap-1.5 overflow-x-auto scroll-fade">
                {filters.map((f) => {
                  const on = f.id === active.id;
                  return (
                    <button
                      key={f.id}
                      type="button"
                      aria-pressed={on}
                      onClick={() => setFilter(f.id)}
                      className={clsx('tap inline-flex h-8 shrink-0 cursor-pointer items-center gap-1.5 rounded-full px-3 text-[12.5px] font-semibold transition-colors duration-150', on ? 'bg-brand-500/40 text-ink' : 'text-soft hover:bg-white/[0.06] hover:text-ink')}
                    >
                      {f.label}
                      <span className={clsx('tabular-nums', on ? 'text-accent' : 'text-mute')}>{fromProvider.filter((e) => matches(f, e)).length}</span>
                    </button>
                  );
                })}
              </div>
              <div role="group" aria-label="Filter by mailbox" className="mt-2 flex gap-1.5">
                {(['all', 'gmail', 'outlook'] as const).map((p) => (
                  <button
                    key={p}
                    type="button"
                    aria-pressed={provider === p}
                    onClick={() => setProvider(p)}
                    className={clsx('tap inline-flex h-7 cursor-pointer items-center rounded-full border px-2.5 text-[12px] font-semibold transition-colors duration-150', provider === p ? 'border-accent/50 text-ink' : 'border-line text-mute hover:text-ink')}
                  >
                    {p === 'all' ? 'Both mailboxes' : p === 'gmail' ? 'Gmail' : 'Outlook'}
                  </button>
                ))}
              </div>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-2.5">
              {missing.length > 0 && (
                <p role="alert" className="mb-2.5 rounded-lg border border-warn/30 bg-warn/[0.08] px-3 py-2 text-[12.5px] text-warn" data-testid="inbox-incomplete">
                  {missing.join('; ')}. Its mail is missing from this list.
                </p>
              )}
              {emails.loading && <SkeletonRows rows={6} />}
              {!emails.loading && visible.length === 0 && (
                <EmptyState icon={Inbox} title="Nothing here">
                  {live && all.length === 0 ? 'No recent mail in the connected mailboxes.' : 'No messages match this filter.'}
                </EmptyState>
              )}
              <ul className="space-y-1.5">
                {visible.map((email) => {
                  const status = EMAIL_STATUS[email.status];
                  const isSelected = email.id === emailId;
                  return (
                    <li key={email.id}>
                      <a
                        href={hrefFor('inbox', email.id)}
                        aria-current={isSelected ? 'true' : undefined}
                        className={clsx('relative block rounded-xl border px-3.5 py-3 transition-colors duration-150', isSelected ? 'border-accent/40 bg-brand-500/20' : 'border-transparent hover:border-line hover:bg-white/[0.04]')}
                      >
                        {/* A rail down the side marks urgent and high-priority mail; the priority is also written out below. */}
                        {(email.priority === 'urgent' || email.priority === 'high') && <span aria-hidden data-testid="priority-rail" className={clsx('absolute bottom-3 left-0 top-3 w-[3px] rounded-full', email.priority === 'urgent' ? 'bg-danger' : 'bg-warn')} />}
                        <span className="flex items-baseline justify-between gap-3">
                          <span className={clsx('flex min-w-0 items-center gap-1.5 text-[13.5px] text-ink', email.unread ? 'font-bold' : 'font-semibold')}>
                            {email.unread && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent"><span className="sr-only">Unread. </span></span>}
                            <span className="truncate">{email.from.name}</span>
                          </span>
                          <span className="shrink-0 text-xs tabular-nums text-mute">{fmtDayTime(email.receivedAt, tz)}</span>
                        </span>
                        <span className="mt-0.5 block truncate text-[13px] text-soft">{email.subject}</span>
                        <span className="mt-0.5 line-clamp-2 text-[12px] leading-[17px] text-mute">{email.summary}</span>
                        <span className="mt-2 flex flex-wrap items-center gap-1.5">
                          {email.status !== 'untracked' && <Pill tone={status.tone}>{status.label}</Pill>}
                          {(email.priority === 'urgent' || email.priority === 'high') && (
                            <Pill tone={PRIORITY[email.priority].tone} icon={null}>
                              {PRIORITY[email.priority].label}
                            </Pill>
                          )}
                          {/* Mail that asks for something gets a chip with its kind; mail that asks for nothing is labelled quietly. */}
                          {email.category === 'fyi' || email.category === 'low_priority' ? (
                            <span className="text-xs text-mute">{EMAIL_CATEGORY[email.category].label}</span>
                          ) : (
                            <Pill tone={EMAIL_CATEGORY[email.category].tone} icon={CATEGORY_ICON[email.category]}>
                              {EMAIL_CATEGORY[email.category].label}
                            </Pill>
                          )}
                          <SourceBadge source={email.provider} className="ml-auto" />
                        </span>
                      </a>
                    </li>
                  );
                })}
              </ul>
            </div>
          </section>

          <section aria-label="Message detail" className={clsx('min-w-0 flex-1 overflow-y-auto', !selected && 'hidden lg:block')}>
            {selected ? (
              selected.source ? <LiveEmailDetail key={selected.id} email={selected} /> : <EmailDetail key={selected.id} email={selected} />
            ) : (
              <div className="flex h-full items-center justify-center p-8">
                <EmptyState icon={Inbox} title="Select a message">
                  {live ? 'Pick a message to see what it needs, the thread, the times you are free for it, and to have a reply drafted.' : 'Pick a message to see its summary, the action items found in it, the thread and any reply the secretary has drafted.'}
                </EmptyState>
              </div>
            )}
          </section>
        </div>
      </WorkspaceState>
    </div>
  );
}
