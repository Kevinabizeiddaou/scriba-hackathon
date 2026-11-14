import clsx from 'clsx'
import { ArrowLeft, Mail, MessageSquarePlus, MessageSquareText, Send, Square, X } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { getErrorMessage } from '../api/client'
import { Button, EmptyState, ErrorNote, PageHeader, SkeletonRows } from '../components/ui'
import { getApi } from '../harness'
import { hrefFor, navigate } from '../lib/router'
import { fmtDayTime, isInstant } from '../lib/time'
import {
  ChatStreamHttpError,
  createChatConversation,
  fetchChatConversations,
  fetchChatMessages,
  postChatMessage,
  postChatMessageStream,
  type ChatMessage,
  type ChatMessageBody,
  type ChatMessagesResponse,
} from './scribaApi'
import { ToolCallCard, chatMessagesKey } from './ToolCallCard'
import { IN_FLIGHT, WORK_QUEUE_KEY, WORK_STAGES, stageOf, type WorkStage } from './workQueue'

const CONVERSATIONS_KEY = ['desk', 'chat', 'conversations'] as const

/** The email a new message is about, handed over by the inbox. Sent with the next message, then cleared. */
export interface ChatContext {
  email_id: string
  thread_id?: string
  provider: string
  subject: string
  prompt?: string
}
let pendingContext: ChatContext | null = null
/** Text to put in the message box of a new conversation, with no email attached. The user still sends it. */
let pendingPrompt: string | null = null
export function openChatAbout(context: ChatContext): void {
  pendingContext = context
  navigate('chat', 'new')
}
export function openChatWithPrompt(prompt: string): void {
  pendingPrompt = prompt
  navigate('chat', 'new')
}

interface Turn {
  /** What the user sent, shown at once. */
  text: string
  /** The reply as it streams. Only text the server sent; nothing is added here. */
  streamed: string
  phase: 'sending' | 'streaming' | 'failed'
  error: string | null
}

/**
 * One line for a reply that carries several actions: how many there are and where each stands,
 * in the order the stages happen. Counts come from the server's statuses and nothing else.
 */
export function summariseSteps(statuses: string[]): string {
  const counts = new Map<WorkStage, number>()
  for (const status of statuses) counts.set(stageOf(status), (counts.get(stageOf(status)) ?? 0) + 1)
  const order: WorkStage[] = ['needs_info', 'awaiting_approval', 'planning', 'executing', 'failed', 'partially_completed', 'completed', 'cancelled', 'unsupported']
  const parts = order.filter(stage => counts.has(stage)).map(stage => `${counts.get(stage)} ${WORK_STAGES[stage].label.toLowerCase()}`)
  return `${statuses.length} actions in this reply: ${parts.join(', ')}.`
}

function Bubble({ message, tz }: { message: ChatMessage; tz: string }) {
  const mine = message.role === 'user'
  const toolCalls = message.tool_calls ?? []
  return (
    <li className={clsx('flex flex-col gap-2', mine ? 'items-end' : 'items-start')}>
      {mine ? <span className="sr-only">You said:</span> : <span className="eyebrow px-1">Secretary</span>}
      {(message.content || toolCalls.length === 0) && (
        <div className={clsx('max-w-[min(680px,92%)] rounded-2xl px-4 py-2.5 text-[13.5px] leading-[21px]', mine ? 'bg-brand-500/70 text-white' : 'border border-line bg-surface text-ink', message.status === 'error' && 'border-danger/40')}>
          <p className="whitespace-pre-wrap break-words">{message.content || (message.status === 'error' ? 'This reply failed.' : '')}</p>
          {message.status === 'error' && <p className="mt-1 text-[12px] text-danger">The server marked this message as failed.</p>}
        </div>
      )}
      {toolCalls.length > 1 && (
        <p className="px-1 text-[12.5px] text-soft" data-testid="steps-summary">{summariseSteps(toolCalls.map(toolCall => toolCall.status))} Each one is decided on its own card.</p>
      )}
      {toolCalls.map((toolCall, index) => (
        <div key={toolCall.id} className="w-full max-w-[680px]">
          {toolCalls.length > 1 && <p className="eyebrow mb-1 px-1">Action {index + 1} of {toolCalls.length}</p>}
          <ToolCallCard toolCall={toolCall} reason={message.content} />
        </div>
      ))}
      {message.created_at && isInstant(message.created_at) && <span className="px-1 text-xs tabular-nums text-mute">{fmtDayTime(message.created_at, tz)}</span>}
    </li>
  )
}

export function LiveChatPage({ conversationId: param }: { conversationId: string | null }) {
  const queryClient = useQueryClient()
  const { info } = getApi()
  const tz = info.principal.timezone
  const conversationId = param && /^\d+$/.test(param) ? Number(param) : null
  const [text, setText] = useState('')
  const [turn, setTurn] = useState<Turn | null>(null)
  const [context, setContext] = useState<ChatContext | null>(null)
  const abort = useRef<AbortController | null>(null)
  const bottom = useRef<HTMLDivElement | null>(null)

  // Pick up the email the inbox handed over, once.
  useEffect(() => {
    if (param === 'new' && pendingPrompt) {
      setText(pendingPrompt)
      pendingPrompt = null
    }
    if (param === 'new' && pendingContext) {
      setContext(pendingContext)
      if (pendingContext.prompt) setText(pendingContext.prompt)
      pendingContext = null
    }
  }, [param])

  const conversations = useQuery({ queryKey: CONVERSATIONS_KEY, queryFn: () => fetchChatConversations(50) })
  const thread = useQuery({
    queryKey: conversationId === null ? ['desk', 'chat', 'messages', 'none'] : chatMessagesKey(conversationId),
    queryFn: () => fetchChatMessages(conversationId!),
    enabled: conversationId !== null,
    // While an approved action is running, follow it; otherwise the thread only changes when the user acts.
    refetchInterval: query => (query.state.data?.messages.some(m => m.tool_calls?.some(t => IN_FLIGHT.has(t.status))) ? 2_500 : false),
  })

  const messages = thread.data?.messages ?? []
  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: 'end' })
  }, [messages.length, turn?.streamed, turn?.phase])
  // Leaving the page stops reading the stream. The server still finishes and stores the turn.
  useEffect(() => () => abort.current?.abort(), [])

  const busy = turn !== null && turn.phase !== 'failed'

  async function send(event?: FormEvent) {
    event?.preventDefault()
    const content = text.trim()
    if (!content || busy) return
    setText('')
    setTurn({ text: content, streamed: '', phase: 'sending', error: null })

    let id = conversationId
    try {
      if (id === null) {
        const created = await createChatConversation()
        id = created.id
        void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_KEY })
      }
    } catch (cause) {
      // Nothing was sent: the text goes back in the box.
      setText(content)
      setTurn({ text: content, streamed: '', phase: 'failed', error: `The conversation could not be started: ${getErrorMessage(cause)}` })
      return
    }

    const body: ChatMessageBody = { content }
    if (context) {
      body.email_id = context.email_id
      body.provider = context.provider
      if (context.thread_id) body.thread_id = context.thread_id
    }
    const key = chatMessagesKey(id)
    const settle = async (target: number) => {
      await queryClient.invalidateQueries({ queryKey: chatMessagesKey(target) })
      void queryClient.invalidateQueries({ queryKey: CONVERSATIONS_KEY })
      void queryClient.invalidateQueries({ queryKey: WORK_QUEUE_KEY })
      setContext(null)
      setTurn(null)
      if (target !== conversationId) navigate('chat', String(target))
    }

    const controller = new AbortController()
    abort.current = controller
    let opened = false
    let finished = false
    let failure: string | null = null
    try {
      await postChatMessageStream(
        id,
        body,
        {
          onOpen: () => { opened = true },
          onStart: () => setTurn(current => (current ? { ...current, phase: 'streaming' } : current)),
          onDelta: delta => setTurn(current => (current ? { ...current, phase: 'streaming', streamed: current.streamed + delta } : current)),
          onReset: () => setTurn(current => (current ? { ...current, streamed: '' } : current)),
          onDone: data => {
            finished = true
            queryClient.setQueryData<ChatMessagesResponse>(key, old => {
              const kept = (old?.messages ?? []).filter(m => m.id !== data.user_message.id && m.id !== data.assistant_message.id)
              return { conversation: data.conversation, messages: [...kept, data.user_message, data.assistant_message] }
            })
          },
          onError: message => { failure = message },
          onTimeout: () => { failure = 'The secretary stopped responding. The server may still finish this turn; the conversation was re-read.' },
        },
        controller.signal,
      )
    } catch (cause) {
      if (!opened) {
        // The stream was never established, so the server did not receive the message: the
        // blocking endpoint is a first attempt, not a repeat. A 401 or 403 is not retried.
        const status = cause instanceof ChatStreamHttpError ? cause.status : null
        if (status === 401 || status === 403) {
          setText(content)
          setTurn({ text: content, streamed: '', phase: 'failed', error: status === 401 ? 'Your Scriba session has ended. Sign in again.' : 'Scriba refused this request.' })
          return
        }
        try {
          const data = await postChatMessage(id, body)
          finished = true
          queryClient.setQueryData<ChatMessagesResponse>(key, old => ({ conversation: data.conversation, messages: [...(old?.messages ?? []), data.user_message, data.assistant_message] }))
        } catch (blocking) {
          setText(content)
          setTurn({ text: content, streamed: '', phase: 'failed', error: `The message was not delivered: ${getErrorMessage(blocking)}` })
          return
        }
      } else {
        failure = `The connection dropped: ${getErrorMessage(cause)}. The message reached the server, so it was not sent again; the conversation was re-read.`
      }
    } finally {
      abort.current = null
    }

    if (failure && !finished) {
      // The server has the user message. Show what it stored instead of sending twice.
      await queryClient.invalidateQueries({ queryKey: key })
      setTurn({ text: content, streamed: '', phase: 'failed', error: failure })
      if (id !== conversationId) navigate('chat', String(id))
      return
    }
    await settle(id)
  }

  function stop() {
    abort.current?.abort()
  }

  const list = conversations.data ?? []
  const showList = conversationId === null && param !== 'new'

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className={clsx(!showList && 'hidden lg:block')}>
        <PageHeader
          title="Secretary chat"
          subtitle="Scriba's own assistant. It reads on its own; anything it would send or change comes back as a card for you to approve."
          actions={
            <a href={hrefFor('chat', 'new')} className="btn btn-secondary">
              <MessageSquarePlus aria-hidden className="h-4 w-4" />
              New conversation
            </a>
          }
        />
      </div>

      <div className="flex min-h-0 flex-1 border-t border-line">
        <aside aria-label="Conversations" className={clsx('w-full min-w-0 flex-col overflow-y-auto p-2.5 lg:flex lg:w-[280px] lg:shrink-0 lg:border-r lg:border-line', showList ? 'flex' : 'hidden')}>
          {conversations.isPending && <SkeletonRows rows={5} />}
          {conversations.isError && <ErrorNote error={new Error(`Conversations could not be loaded: ${getErrorMessage(conversations.error)}`)} onRetry={() => void conversations.refetch()} />}
          {conversations.isSuccess && list.length === 0 && (
            <p className="px-2 py-3 text-[13px] text-soft">No conversations yet. Start one to give the secretary something to do.</p>
          )}
          <ul className="space-y-1">
            {list.map(conversation => {
              const active = conversation.id === conversationId
              const at = conversation.last_message_at ?? conversation.updated_at
              return (
                <li key={conversation.id}>
                  <a href={hrefFor('chat', String(conversation.id))} aria-current={active ? 'true' : undefined} className={clsx('block rounded-xl border px-3 py-2.5 transition-colors duration-150', active ? 'border-accent/40 bg-brand-500/20' : 'border-transparent hover:border-line hover:bg-white/[0.04]')}>
                    <span className="block truncate text-[13.5px] font-semibold text-ink">{conversation.title || 'Untitled conversation'}</span>
                    {at && isInstant(at) && <span className="text-xs tabular-nums text-mute">{fmtDayTime(at, tz)}</span>}
                  </a>
                </li>
              )
            })}
          </ul>
        </aside>

        <section aria-label="Conversation" className={clsx('min-w-0 flex-1 flex-col', showList ? 'hidden lg:flex' : 'flex')}>
          <a href={hrefFor('chat')} className="tap inline-flex items-center gap-1.5 px-4 pt-3 text-[13px] font-medium text-accent hover:underline lg:hidden">
            <ArrowLeft aria-hidden className="h-4 w-4" />
            Conversations
          </a>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4 sm:px-6" aria-live="polite">
            {conversationId !== null && thread.isPending && <SkeletonRows rows={4} />}
            {conversationId !== null && thread.isError && (
              <ErrorNote error={new Error(`This conversation could not be loaded: ${getErrorMessage(thread.error)}`)} onRetry={() => void thread.refetch()} />
            )}
            {conversationId === null && !turn && (
              <EmptyState icon={MessageSquareText} title="Ask the secretary">
                <p>It works on your connected Gmail, Outlook and calendars through Scriba. Nothing is sent or changed without your approval.</p>
                <ul className="mt-3 space-y-1.5">
                  {info.suggestedPrompts.map(prompt => (
                    <li key={prompt}>
                      <button type="button" onClick={() => setText(prompt)} className="tap cursor-pointer rounded-full border border-line px-3 py-1 text-[12.5px] text-ink hover:border-accent/50">
                        {prompt}
                      </button>
                    </li>
                  ))}
                </ul>
              </EmptyState>
            )}
            <ol className="mx-auto max-w-3xl space-y-4">
              {messages.filter(message => message.role !== 'system').map(message => (
                <Bubble key={message.id} message={message} tz={tz} />
              ))}
              {turn && (
                <>
                  {/* The user's words appear at once; they are replaced by the stored message when the turn ends. */}
                  {!messages.some(m => m.role === 'user' && m.content === turn.text && turn.phase === 'failed') && (
                    <li className="flex justify-end">
                      <div className="max-w-[min(680px,92%)] rounded-2xl bg-brand-500/70 px-4 py-2.5 text-[13.5px] leading-[21px] text-white">
                        <p className="whitespace-pre-wrap break-words">{turn.text}</p>
                      </div>
                    </li>
                  )}
                  {turn.phase !== 'failed' && (
                    <li className="flex justify-start" data-testid="streaming-reply">
                      <div className="max-w-[min(680px,92%)] rounded-2xl border border-line bg-surface px-4 py-2.5 text-[13.5px] leading-[21px] text-ink">
                        {turn.streamed ? (
                          <p className="whitespace-pre-wrap break-words">{turn.streamed}</p>
                        ) : (
                          <p role="status" className="flex items-center gap-2 text-soft">
                            <span aria-hidden className="pulse-dot h-1.5 w-1.5 rounded-full bg-accent" />
                            {turn.phase === 'sending' ? 'Sending…' : 'The secretary is working…'}
                          </p>
                        )}
                      </div>
                    </li>
                  )}
                  {turn.phase === 'failed' && turn.error && (
                    <li>
                      <div role="alert" className="flex flex-wrap items-center gap-3 rounded-btn border border-danger/30 bg-danger/[0.08] px-3.5 py-2.5 text-[13px] text-danger">
                        <span className="min-w-0 flex-1">{turn.error}</span>
                        <Button variant="ghost" className="h-7 px-2 text-danger" onClick={() => setTurn(null)}>Dismiss</Button>
                      </div>
                    </li>
                  )}
                </>
              )}
            </ol>
            <div ref={bottom} />
          </div>

          <form onSubmit={send} className="border-t border-line bg-sunken/50 px-4 py-3 sm:px-6">
            <div className="mx-auto max-w-3xl">
              {context && (
                <p className="mb-2 flex items-center gap-2 rounded-lg border border-line bg-white/[0.04] px-3 py-1.5 text-[12.5px] text-soft">
                  <Mail aria-hidden className="h-3.5 w-3.5 shrink-0 text-accent" />
                  <span className="min-w-0 flex-1 truncate">About: {context.subject}</span>
                  <button type="button" aria-label="Remove the email from this message" onClick={() => setContext(null)} className="tap inline-flex cursor-pointer items-center justify-center text-mute hover:text-ink">
                    <X aria-hidden className="h-3.5 w-3.5" />
                  </button>
                </p>
              )}
              <div className="flex items-end gap-2">
                <label htmlFor="chat-input" className="sr-only">Message the secretary</label>
                <textarea
                  id="chat-input"
                  rows={2}
                  value={text}
                  onChange={event => setText(event.target.value)}
                  onKeyDown={event => {
                    if (event.key === 'Enter' && !event.shiftKey) {
                      event.preventDefault()
                      void send()
                    }
                  }}
                  placeholder="Ask for a briefing, a reply, a meeting time, a task…"
                  className="field min-h-[44px] flex-1 resize-none"
                />
                {busy ? (
                  <Button variant="secondary" icon={Square} onClick={stop} aria-label="Stop reading the reply">Stop</Button>
                ) : (
                  <Button variant="primary" icon={Send} type="submit" disabled={!text.trim()}>Send</Button>
                )}
              </div>
              {busy && <p className="mt-1.5 text-xs text-mute">Stop only stops showing the reply. The server finishes the turn, and it appears when you reopen the conversation.</p>}
            </div>
          </form>
        </section>
      </div>
    </div>
  )
}
