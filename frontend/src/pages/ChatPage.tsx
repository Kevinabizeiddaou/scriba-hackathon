import clsx from 'clsx';
import { MessageSquarePlus, MessageSquareText, RotateCcw, SendHorizontal } from 'lucide-react';
import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { getApi } from '../harness';
import type { AgentRun, ApprovalRequest, ConversationMessage } from '../harness/types';
import { ApprovalCard } from '../components/ApprovalCard';
import { RunCard } from '../components/RunCard';
import { Button, EmptyState, ErrorNote, SkeletonRows } from '../components/ui';
import { navigate } from '../lib/router';
import { fmtDayTime, fmtTime } from '../lib/time';
import { useResource } from '../lib/useResource';

function AssistantAvatar() {
  return (
    <span aria-hidden className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-gradient-to-br from-brand-400 to-brand-600 text-xs font-bold text-white">
      S
    </span>
  );
}

interface MessageProps {
  message: ConversationMessage;
  run: AgentRun | undefined;
  approvals: ApprovalRequest[];
  timeZone: string;
  /** Sends the request behind this reply again. Only offered on the latest reply, and only after a failure. */
  onRetry?: () => Promise<unknown>;
}

function Message({ message, run, approvals, timeZone, onRetry }: MessageProps) {
  if (message.role === 'user') {
    return (
      <li className="rise-in flex justify-end">
        <div className="max-w-[min(560px,85%)]">
          <p className="whitespace-pre-wrap rounded-2xl rounded-br-md bg-brand-600 px-4 py-2.5 text-[14px] leading-[22px] text-white">{message.text}</p>
          <p className="mt-1 text-right text-xs tabular-nums text-mute">{fmtTime(message.createdAt, timeZone)}</p>
        </div>
      </li>
    );
  }
  const working = message.status === 'streaming';
  return (
    <li className="rise-in flex gap-3">
      <AssistantAvatar />
      <div className="min-w-0 max-w-[min(680px,100%)] flex-1 space-y-2.5">
        <div>
          <p className="text-[12px] font-semibold text-soft">
            Scriba <span className="font-normal tabular-nums text-mute">· {fmtTime(message.createdAt, timeZone)}</span>
          </p>
          {working ? (
            <p className="mt-1 flex items-center gap-2 text-[14px] text-soft" role="status">
              <span className="flex gap-1" aria-hidden>
                {[0, 1, 2].map((i) => (
                  <span key={i} className="pulse-dot h-1.5 w-1.5 rounded-full bg-accent" style={{ animationDelay: `${i * 160}ms` }} />
                ))}
              </span>
              Working on it
            </p>
          ) : (
            <p className="mt-1 whitespace-pre-wrap text-[14px] leading-[22px] text-ink">{message.text}</p>
          )}
        </div>
        {run && (run.actions.length > 0 || working) && <RunCard run={run} timeZone={timeZone} defaultOpen={working || run.status === 'awaiting_approval'} />}
        {approvals.map((approval) => (
          <ApprovalCard key={approval.id} approval={approval} run={run} origin={null} compact onRetry={onRetry} />
        ))}
        {onRetry && run?.status === 'failed' && !approvals.some((a) => a.execution.status === 'failed') && (
          <div role="alert" className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-danger/25 bg-danger/[0.07] px-3.5 py-2.5">
            <p className="text-[12.5px] text-soft">This request did not finish. Nothing is repeated automatically.</p>
            <Button variant="secondary" icon={RotateCcw} onClick={() => void onRetry()}>
              Try again
            </Button>
          </div>
        )}
      </div>
    </li>
  );
}

export function ChatPage({ conversationId }: { conversationId: string | null }) {
  const api = getApi();
  const { principal, suggestedPrompts, dataSource } = api.info;
  const conversations = useResource((a) => a.listConversations(), []);
  const activeId = conversationId ?? conversations.data?.[0]?.id ?? null;

  const thread = useResource(
    async (a) => {
      if (!activeId) return null;
      const [messages, runs, approvals] = await Promise.all([a.listMessages(activeId), a.listRuns({ conversationId: activeId }), a.listApprovals()]);
      return { messages, runs, approvals: approvals.filter((x) => x.conversationId === activeId) };
    },
    [activeId],
  );

  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<Error | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const input = useRef<HTMLTextAreaElement>(null);

  const runsById = useMemo(() => new Map((thread.data?.runs ?? []).map((r) => [r.id, r])), [thread.data]);
  const busy = (thread.data?.runs ?? []).some((r) => r.status === 'running' || r.status === 'queued');
  // Scroll to the newest content whenever the thread grows or a run moves on.
  const signature = thread.data ? `${thread.data.messages.length}:${thread.data.runs.map((r) => `${r.status}${r.actions.length}`).join(',')}:${thread.data.approvals.map((a) => a.status).join(',')}` : '';
  useEffect(() => {
    scroller.current?.scrollTo?.({ top: scroller.current.scrollHeight });
  }, [signature]);

  async function send(text: string) {
    const trimmed = text.trim();
    // `busy` is checked here as well as on the button, because Enter does not go through the button.
    if (!trimmed || sending || busy) return;
    setSending(true);
    setSendError(null);
    try {
      let id = activeId;
      if (!id) {
        id = (await api.createConversation()).id;
        navigate('chat', id);
      }
      await api.sendMessage(id, trimmed);
      setDraft('');
    } catch (cause) {
      setSendError(cause instanceof Error ? cause : new Error(String(cause)));
    } finally {
      setSending(false);
      input.current?.focus();
    }
  }

  async function startNew() {
    try {
      const created = await api.createConversation();
      navigate('chat', created.id);
      input.current?.focus();
    } catch (cause) {
      setSendError(cause instanceof Error ? cause : new Error(String(cause)));
    }
  }

  const onSubmit = (event: FormEvent) => {
    event.preventDefault();
    void send(draft);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void send(draft);
    }
  };

  const messages = thread.data?.messages ?? [];
  const lastAsked = messages.filter((m) => m.role === 'user').at(-1);
  const approvalsFor = (message: ConversationMessage) => (message.role === 'assistant' && message.runId ? (thread.data?.approvals ?? []).filter((a) => a.runId === message.runId) : []);

  return (
    <div className="flex h-full min-h-0">
      {/* Conversation history */}
      <aside aria-label="Conversations" className="hidden w-[272px] shrink-0 flex-col border-r border-line md:flex">
        <div className="flex items-center justify-between px-4 pb-3 pt-5">
          <h2 className="eyebrow">Conversations</h2>
          <Button variant="ghost" icon={MessageSquarePlus} className="h-8 px-2.5" onClick={startNew}>
            New
          </Button>
        </div>
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto px-2.5 pb-4">
          {conversations.loading && <SkeletonRows rows={3} />}
          {conversations.error && <ErrorNote error={conversations.error} onRetry={conversations.reload} />}
          {conversations.data?.map((c) => {
            const active = c.id === activeId;
            return (
              <a
                key={c.id}
                href={`#/chat/${encodeURIComponent(c.id)}`}
                aria-current={active ? 'true' : undefined}
                className={clsx('block rounded-btn px-3 py-2.5 transition-colors duration-150', active ? 'bg-brand-500/25 shadow-[inset_2px_0_0_var(--accent)]' : 'hover:bg-white/[0.05]')}
              >
                <span className="block truncate text-[13.5px] font-semibold text-ink">{c.title}</span>
                <span className="mt-0.5 block truncate text-[12px] text-mute">{c.lastMessagePreview ?? 'No messages yet'}</span>
                <span className="mt-0.5 block text-xs tabular-nums text-mute">{fmtDayTime(c.updatedAt, principal.timezone)}</span>
              </a>
            );
          })}
        </div>
      </aside>

      {/* Thread */}
      <section aria-label="Conversation" className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-3 sm:px-6">
          <div className="min-w-0">
            <h1 className="truncate text-[16px] font-bold text-ink">{conversations.data?.find((c) => c.id === activeId)?.title ?? 'Secretary chat'}</h1>
            <p className="hidden text-[12px] text-mute sm:block">Ask Scriba to handle mail, meetings, tasks and reminders. Anything that sends or changes something waits for your approval.</p>
          </div>
          <div className="flex shrink-0 items-center gap-2 md:hidden">
            {conversations.data && conversations.data.length > 1 && (
              <select aria-label="Switch conversation" value={activeId ?? ''} onChange={(e) => navigate('chat', e.target.value)} className="field h-9 max-w-[150px] py-0 text-[13px]">
                {conversations.data.map((c) => (
                  <option key={c.id} value={c.id} className="bg-surface">
                    {c.title}
                  </option>
                ))}
              </select>
            )}
            <Button variant="secondary" icon={MessageSquarePlus} aria-label="New conversation" className="tap px-2.5" onClick={startNew} />
          </div>
        </div>

        <div ref={scroller} className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-6">
          {thread.loading && <SkeletonRows rows={3} />}
          {thread.error && <ErrorNote error={thread.error} onRetry={thread.reload} />}
          {!thread.loading && messages.length === 0 && (
            <div className="mx-auto mt-8 max-w-lg">
              <EmptyState icon={MessageSquareText} title="What should Scriba take care of?">
                Describe it in your own words: a meeting to arrange, a reply to draft, something to be reminded of. Scriba checks your calendars, proposes what to do, and asks before it sends or changes anything.
              </EmptyState>
            </div>
          )}
          <ol className="mx-auto max-w-3xl space-y-5">
            {messages.map((message) => {
              const run = message.runId ? runsById.get(message.runId) : undefined;
              // Only the latest request can be retried, by sending the message that asked for it once more.
              const asked = message.role === 'assistant' && run?.status === 'failed' && lastAsked?.runId === message.runId ? lastAsked : undefined;
              return <Message key={message.id} message={message} run={run} approvals={approvalsFor(message)} timeZone={principal.timezone} onRetry={asked ? () => send(asked.text) : undefined} />;
            })}
          </ol>
        </div>

        <div className="border-t border-line bg-sunken/50 px-4 py-3 sm:px-6">
          <div className="mx-auto max-w-3xl">
            {sendError && (
              <div className="mb-2">
                <ErrorNote error={sendError} />
              </div>
            )}
            {suggestedPrompts.length > 0 && (
              <div className="mb-2.5 flex gap-2 overflow-x-auto scroll-fade pb-1" aria-label="Suggested prompts">
                {suggestedPrompts.map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    disabled={sending || busy}
                    onClick={() => void send(prompt)}
                    className="tap max-w-[280px] shrink-0 cursor-pointer truncate rounded-full border border-line-strong bg-white/[0.04] px-3 py-1.5 text-[12.5px] text-soft transition-colors duration-150 hover:bg-white/[0.09] hover:text-ink disabled:cursor-not-allowed disabled:opacity-45"
                    title={prompt}
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            )}
            <form onSubmit={onSubmit} className="flex items-end gap-2">
              <label htmlFor="chat-input" className="sr-only">
                Message Scriba
              </label>
              <textarea
                id="chat-input"
                ref={input}
                rows={1}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={onKeyDown}
                placeholder="Message Scriba"
                className="field max-h-40 min-h-[40px] flex-1 resize-none text-[14px]"
              />
              <Button type="submit" variant="primary" icon={SendHorizontal} busy={sending} disabled={!draft.trim() || busy} className="h-10">
                Send
              </Button>
            </form>
            <p className="mt-1.5 text-xs text-mute">
              Enter to send, Shift+Enter for a new line.
              {dataSource === 'simulated' && ' Mock mode answers the suggested prompts only.'}
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
