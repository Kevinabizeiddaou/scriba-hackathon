import clsx from 'clsx';
import { ShieldCheck } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { getApi } from '../harness';
import { ApprovalCard } from '../components/ApprovalCard';
import { EmptyState, ErrorNote, PageHeader, SkeletonRows } from '../components/ui';
import { hrefFor } from '../lib/router';
import { useResource } from '../lib/useResource';

export function ApprovalsPage({ approvalId }: { approvalId: string | null }) {
  const [tab, setTab] = useState<'pending' | 'decided'>('pending');
  const data = useResource(async (api) => {
    const [approvals, requests, conversations, runs] = await Promise.all([api.listApprovals(), api.listRequests(), api.listConversations(), api.listRuns()]);
    return { approvals, requests, conversations, runs };
  }, []);

  const approvals = data.data?.approvals ?? [];
  const pending = approvals.filter((a) => a.status === 'pending');
  const decided = approvals
    .filter((a) => a.status !== 'pending')
    .sort((a, b) => Date.parse(b.decidedAt ?? b.createdAt) - Date.parse(a.decidedAt ?? a.createdAt));
  // A card you have just decided stays where it is, so you can watch it execute.
  // It moves to "Decided" the next time you open this tab.
  const keptInPending = useRef(new Set<string>());
  for (const a of pending) keptInPending.current.add(a.id);
  const pendingView = approvals.filter((a) => keptInPending.current.has(a.id));
  const shown = tab === 'pending' ? pendingView : decided;

  // A deep link opens the tab that holds the approval and scrolls to it, once.
  const linked = approvalId ? approvals.find((a) => a.id === approvalId) : undefined;
  const handledLink = useRef<string | null>(null);
  useEffect(() => {
    if (!linked || handledLink.current === linked.id) return;
    handledLink.current = linked.id;
    setTab(linked.status === 'pending' ? 'pending' : 'decided');
    const frame = requestAnimationFrame(() => document.getElementById(`approval-${linked.id}`)?.scrollIntoView?.({ block: 'start', behavior: 'smooth' }));
    return () => cancelAnimationFrame(frame);
  }, [linked]);

  function openTab(next: 'pending' | 'decided') {
    if (next === 'pending' && tab !== 'pending') keptInPending.current = new Set(pending.map((a) => a.id));
    setTab(next);
  }

  function originOf(requestId: string | null, conversationId: string | null) {
    if (requestId) {
      const request = data.data?.requests.find((r) => r.id === requestId);
      if (request) return { label: `${request.from.name}: ${request.subject}`, href: hrefFor('inbox', request.id) };
      // Reply drafts and follow-up reminders come from the workspace, not from a meeting request.
      return requestId.startsWith('fu-') ? { label: 'a follow-up', href: hrefFor('tasks', 'followups') } : { label: 'an email in the inbox', href: hrefFor('inbox', requestId) };
    }
    if (conversationId) {
      const conversation = data.data?.conversations.find((c) => c.id === conversationId);
      return conversation ? { label: `chat: ${conversation.title}`, href: hrefFor('chat', conversation.id) } : null;
    }
    return null;
  }

  /** Only a meeting request can be handed back to the secretary; a failed request is open for processing again. */
  function retryFor(requestId: string | null) {
    const request = requestId ? data.data?.requests.find((r) => r.id === requestId) : undefined;
    if (!request || (request.status !== 'failed' && request.status !== 'escalated')) return undefined;
    return () => getApi().processRequest(request.id);
  }

  return (
    <div>
      <PageHeader
        title="Approval Center"
        subtitle="Nothing is sent and no calendar is changed until you approve it here. Each card shows exactly what will happen and why."
      />
      <div className="px-4 pb-10 sm:px-6 lg:px-8">
        <div role="tablist" aria-label="Approvals" className="mb-4 inline-flex rounded-full border border-line bg-sunken/60 p-1">
          {(
            [
              ['pending', 'Waiting for you', pending.length],
              ['decided', 'Decided', decided.length],
            ] as const
          ).map(([id, label, n]) => (
            <button
              key={id}
              id={`tab-${id}`}
              role="tab"
              type="button"
              aria-selected={tab === id}
              aria-controls="approvals-panel"
              onClick={() => openTab(id)}
              className={clsx(
                'tap inline-flex h-8 cursor-pointer items-center gap-2 rounded-full px-3.5 text-[13px] font-semibold transition-colors duration-150',
                tab === id ? 'bg-brand-500/50 text-ink' : 'text-soft hover:text-ink',
              )}
            >
              {label}
              <span className={clsx('tabular-nums', tab === id ? 'text-accent' : 'text-mute')}>{n}</span>
            </button>
          ))}
        </div>

        <div id="approvals-panel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="mx-auto max-w-3xl space-y-4 lg:mx-0">
          {data.loading && <SkeletonRows rows={3} />}
          {data.error && <ErrorNote error={data.error} onRetry={data.reload} />}
          {!data.loading && shown.length === 0 && (
            <EmptyState icon={ShieldCheck} title={tab === 'pending' ? 'Nothing is waiting for you' : 'No decisions yet'}>
              {tab === 'pending' ? 'When the agent wants to send an email or change your calendar, the proposal appears here first.' : 'Approvals you approve or reject are kept here with what was executed.'}
            </EmptyState>
          )}
          {shown.map((approval) => (
            <ApprovalCard
              key={approval.id}
              approval={approval}
              run={data.data?.runs.find((r) => r.id === approval.runId)}
              origin={originOf(approval.requestId, approval.conversationId)}
              highlighted={approval.id === approvalId}
              onRetry={retryFor(approval.requestId)}
            />
          ))}
        </div>
      </div>
    </div>
  );
}
