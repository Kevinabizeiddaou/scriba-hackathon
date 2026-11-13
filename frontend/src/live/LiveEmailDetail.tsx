import clsx from 'clsx'
import { ArrowLeft, CalendarCheck, FilePen, MessageSquareText, ShieldAlert, Trash2 } from 'lucide-react'
import { useEffect } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { getErrorMessage } from '../api/client'
import { fetchDeskInboxItem, type DeskInboxItem, type Triage } from '../api/desk'
import { Button, ErrorNote, Pill, SkeletonRows } from '../components/ui'
import { EMAIL_CATEGORY, SourceBadge } from '../components/workspace'
import { getApi } from '../harness'
import type { InboxEmail } from '../harness/workspace'
import { PRIORITY } from '../lib/labels'
import { hrefFor } from '../lib/router'
import { fmtDayTime, fmtRange } from '../lib/time'
import { openChatAbout } from './LiveChatPage'
import { toThreadMessage } from './mappers'
import { createDraftFromRequest, discardDraft, fetchDrafts, type ScribaDraft } from './scribaApi'
import { useRequiredLiveSession } from './session'

const REASON_LABEL: Record<string, string> = {
  question: 'asks a question',
  direct_request: 'makes a direct request',
  meeting_request: 'asks for a meeting',
  deadline: 'mentions a deadline',
  urgent: 'is marked urgent',
  bulk: 'looks like bulk mail',
  automated: 'is automated',
  no_question_or_request: 'has no question or request in it',
  newsletter: 'looks like a newsletter',
  no_reply_sender: 'comes from a no-reply address',
}

const OUTCOME_LABEL: Record<Triage['outcome'], string> = {
  schedule: 'Arrange a meeting',
  reply: 'Write a reply',
  task: 'Record a task',
  none: 'Nothing to do',
}

const INCOMPLETE: Record<string, string> = {
  no_calendar_connected: 'No calendar is connected, so no time can be offered.',
  calendar_unreadable: 'A connected calendar could not be read, so no time is offered. A calendar that cannot be read is never treated as free.',
  invalid_preferences: "Your working-hours preferences in Scriba could not be used, so no time is offered.",
}

const draftsKey = ['desk', 'drafts'] as const

function Draft({ draft, onDiscard, discarding }: { draft: ScribaDraft; onDiscard: () => void; discarding: boolean }) {
  return (
    <section className="card border-warn/25 p-4" aria-label="Reply draft">
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <h3 className="eyebrow">Reply draft, stored in Scriba</h3>
        <Pill tone="neutral">Draft, not sent</Pill>
      </div>
      <p className="whitespace-pre-wrap rounded-lg border border-line bg-bg/60 px-3 py-2.5 text-[13.5px] leading-[21px] text-ink">{draft.final_text || draft.draft_text || 'The draft has no text.'}</p>
      {(draft.calendar_context?.suggested_slots?.length ?? 0) > 0 && (
        <p className="mt-2 text-[12.5px] text-soft">Times it relies on: {draft.calendar_context!.suggested_slots!.map(slot => slot.label || `${slot.start} to ${slot.end}`).join('; ')}</p>
      )}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-3">
        <p className="min-w-0 flex-1 text-[12px] text-mute">Sending from the Desk is switched off until the backend reports its safety fixes. The draft stays in Scriba for review; nothing has been sent.</p>
        <Button variant="ghost" icon={Trash2} onClick={onDiscard} busy={discarding}>Discard draft</Button>
      </div>
    </section>
  )
}

export function LiveEmailDetail({ email }: { email: InboxEmail }) {
  const session = useRequiredLiveSession()
  const queryClient = useQueryClient()
  const { principal } = getApi().info
  const tz = principal.timezone
  const source = email.source!
  const triage = source.triage

  const item = useQuery<DeskInboxItem>({
    queryKey: ['desk', 'inbox-item', email.id],
    // The mailbox goes with the message: the same provider and account it arrived in.
    queryFn: () => fetchDeskInboxItem(email.provider, source.messageId, { mailbox: email.account || undefined }),
  })
  const drafts = useQuery({ queryKey: draftsKey, queryFn: fetchDrafts })
  const draft = drafts.data?.find(d => d.email_id === source.messageId && (d.status ?? 'draft') !== 'sent' && (d.status ?? '') !== 'discarded') ?? null

  useEffect(() => {
    session.desk.setTimeZone(item.data?.calendar?.timezone)
  }, [item.data?.calendar?.timezone, session.desk])

  const create = useMutation({
    mutationFn: () => createDraftFromRequest(item.data!.draftRequest!),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: draftsKey }),
  })
  const discard = useMutation({
    mutationFn: () => discardDraft(draft!.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: draftsKey }),
  })

  const calendar = item.data?.calendar ?? null
  const replyFrom = item.data?.replyFrom
  const own = [principal.email, email.account]
  const askChat = (prompt: string) => openChatAbout({ email_id: source.messageId, thread_id: email.threadId, provider: email.provider, subject: email.subject, prompt })

  return (
    <article className="space-y-4 p-4 sm:p-6" aria-label={`Email: ${email.subject}`}>
      <a href={hrefFor('inbox')} className="tap inline-flex items-center gap-1.5 text-[13px] font-medium text-accent hover:underline lg:hidden">
        <ArrowLeft aria-hidden className="h-4 w-4" />
        Inbox
      </a>

      <header>
        <h2 className="text-[19px] font-bold leading-7 text-ink">{email.subject}</h2>
        <p className="mt-0.5 text-[13px] text-soft">
          {email.from.name} {email.from.email && email.from.email !== email.from.name && <span className="text-mute">&lt;{email.from.email}&gt;</span>}
        </p>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[12px] text-mute">
          <span className="tabular-nums">Received {fmtDayTime(email.receivedAt, tz)}</span>
          <SourceBadge source={email.provider} />
          {email.account && <span>in {email.account}</span>}
        </p>
        <div className="mt-3 flex flex-wrap gap-1.5">
          <Pill tone={EMAIL_CATEGORY[email.category].tone} icon={null}>{EMAIL_CATEGORY[email.category].label}</Pill>
          <Pill tone={PRIORITY[email.priority].tone} icon={null}>{PRIORITY[email.priority].label} priority</Pill>
          {triage.has_deadline && <Pill tone="warn">Mentions a deadline</Pill>}
          {triage.meeting_intent && triage.meeting_intent !== 'new' && <Pill tone="info" icon={null}>{triage.meeting_intent === 'reschedule' ? 'Reschedule' : 'Cancellation'}</Pill>}
        </div>
      </header>

      <section className="card p-4" aria-label="Triage">
        <h3 className="eyebrow mb-2">What the secretary made of it</h3>
        <dl className="space-y-1.5 text-[13px]">
          <div className="flex gap-3">
            <dt className="w-[92px] shrink-0 text-mute">Next step</dt>
            <dd className="font-semibold text-ink">{OUTCOME_LABEL[triage.outcome]}</dd>
          </div>
          {triage.reasons.length > 0 && (
            <div className="flex gap-3">
              <dt className="w-[92px] shrink-0 text-mute">Because it</dt>
              <dd className="text-ink">{triage.reasons.map(reason => REASON_LABEL[reason] ?? reason.replace(/_/g, ' ')).join(', ')}</dd>
            </div>
          )}
          {replyFrom && (
            <div className="flex gap-3">
              <dt className="w-[92px] shrink-0 text-mute">Reply from</dt>
              <dd className="min-w-0 break-words text-ink">
                {replyFrom.provider === 'gmail' ? 'Gmail' : 'Outlook'}{replyFrom.providerAccountId ? ` · ${replyFrom.providerAccountId}` : ''}
                {!source.replySupported && <span className="ml-2 text-warn">Scriba cannot reply to this message.</span>}
              </dd>
            </div>
          )}
        </dl>
        <p className="mt-2.5 text-[12px] text-mute">Classified by rules from the subject and preview, without a model. It can be wrong; ask in chat for a reading of the full message.</p>
        <div className="mt-3 flex flex-wrap gap-2 border-t border-line pt-3">
          <Button icon={MessageSquareText} onClick={() => askChat(triage.outcome === 'schedule' ? 'Find a time for this meeting request and draft a reply offering it.' : triage.outcome === 'task' ? 'Record a task for what this email asks me to do.' : 'Draft a reply to this email.')}>
            Hand to the secretary in chat
          </Button>
        </div>
      </section>

      {item.isPending && <SkeletonRows rows={3} />}
      {item.isError && <ErrorNote error={new Error(`The thread and calendar check could not be loaded: ${getErrorMessage(item.error)}`)} onRetry={() => void item.refetch()} />}

      {calendar && (
        <section className={clsx('card p-4', !calendar.complete && 'border-warn/30')} aria-label="Availability">
          <h3 className="eyebrow mb-2 flex items-center gap-1.5">
            {calendar.complete ? <CalendarCheck aria-hidden className="h-3.5 w-3.5 text-ok" /> : <ShieldAlert aria-hidden className="h-3.5 w-3.5 text-warn" />}
            Free on every connected calendar
          </h3>
          {!calendar.complete ? (
            <p role="alert" className="text-[13px] text-warn">{INCOMPLETE[calendar.reason ?? ''] ?? 'Availability could not be established, so no time is offered.'}</p>
          ) : calendar.slots.length === 0 ? (
            <p className="text-[13px] text-soft">No free time inside your working hours in the next working days.</p>
          ) : (
            <ul className="space-y-1 text-[13px] tabular-nums text-ink">
              {calendar.slots.map(slot => <li key={slot.start}>{fmtRange(slot.start, slot.end, tz)}</li>)}
            </ul>
          )}
          <ul className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-mute">
            {calendar.calendars.map(read => (
              <li key={`${read.provider}:${read.account}`} className={clsx(!read.ok && 'text-warn')}>
                {read.provider === 'google' ? 'Google Calendar' : 'Outlook Calendar'} ({read.account}): {read.ok ? 'read' : `not read: ${read.error ?? 'error'}`}
              </li>
            ))}
          </ul>
        </section>
      )}

      {draft && <Draft draft={draft} onDiscard={() => discard.mutate()} discarding={discard.isPending} />}
      {discard.isError && <ErrorNote error={new Error(`The draft was not discarded: ${getErrorMessage(discard.error)}`)} />}

      {item.data?.draftRequest && !draft && (
        <section className="card p-4" aria-label="Draft a reply">
          <h3 className="eyebrow mb-2">Reply</h3>
          <p className="text-[13px] text-soft">
            Scriba can write a reply draft for review. {calendar?.complete ? 'For this meeting request it may only offer the times verified free above.' : calendar ? 'Because availability is not established, it is told not to confirm a time.' : ''} The draft is stored in Scriba. Nothing is sent.
          </p>
          {create.isError && (
            <div className="mt-3">
              <ErrorNote error={new Error(`No draft was written: ${getErrorMessage(create.error)}`)} />
            </div>
          )}
          <div className="mt-3">
            <Button variant="primary" icon={FilePen} onClick={() => create.mutate()} busy={create.isPending} disabled={create.isPending}>
              Write a draft for review
            </Button>
          </div>
        </section>
      )}

      {item.data && (
        <section className="card p-4" aria-label="Thread">
          <h3 className="eyebrow mb-1">
            Thread · {item.data.thread.count} {item.data.thread.count === 1 ? 'message' : 'messages'} in the recent inbox
          </h3>
          <p className="mb-3 text-[12px] text-mute">Each message shows the provider's preview, not its full text. Older messages of the thread are not listed.</p>
          <ol className="space-y-3">
            {item.data.thread.messages.map(raw => {
              const message = toThreadMessage(raw, own)
              return (
                <li key={message.id} className={clsx('rounded-xl border px-3.5 py-3', message.outbound ? 'ml-6 border-brand-500/40 bg-brand-500/[0.12]' : 'mr-6 border-line bg-white/[0.025]')}>
                  <p className="flex flex-wrap items-baseline justify-between gap-x-3 text-[12px]">
                    <span className="font-semibold text-ink">
                      {message.from.name}
                      {message.outbound && <span className="ml-1.5 font-normal text-mute">(from your mailbox)</span>}
                    </span>
                    <span className="tabular-nums text-mute">{fmtDayTime(message.sentAt, tz)}</span>
                  </p>
                  <p className="mt-1.5 whitespace-pre-wrap text-[13.5px] leading-[21px] text-ink">{message.bodyText}</p>
                </li>
              )
            })}
          </ol>
        </section>
      )}
    </article>
  )
}
