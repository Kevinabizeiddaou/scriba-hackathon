/**
 * Scriba endpoints the Desk workspace uses beyond the ones in src/api/scriba.ts and
 * src/api/desk.ts (which the backend owner maintains and which are not edited here).
 *
 * Every path, body and field below is Scriba's own, read from its frontend client and types at
 * commit 3ae3a2aa (Gmail/frontend/src/api/index.ts, Gmail/frontend/src/types/index.ts) and from
 * the routes in Gmail/apps/api. Fields the Desk does not use are left out, not guessed. In
 * docs/BACKEND_CONTRACT.md these are the "Read" endpoints of section 3.
 *
 * The session is Scriba's HttpOnly cookie: axios is configured with withCredentials in
 * src/api/client.ts, and the one fetch() here sends credentials: 'include'.
 */
import { backendUrl, getJson, postJson } from '../api/client'
import type { DraftRequest } from '../api/desk'

// ── Chat ────────────────────────────────────────────────────────────────────

export type ChatToolStatus =
  | 'pending'
  | 'needs_info'
  | 'draft'
  | 'awaiting_approval'
  | 'approved'
  | 'executing'
  | 'executed'
  | 'partially_executed'
  | 'failed'
  | 'cancelled'
  | 'unsupported'

export const CHAT_TOOL_STATUSES: readonly ChatToolStatus[] = [
  'pending', 'needs_info', 'draft', 'awaiting_approval', 'approved', 'executing',
  'executed', 'partially_executed', 'failed', 'cancelled', 'unsupported',
]

export interface ChatToolCall {
  id: number
  message_id: number
  conversation_id: number
  tool_name: string
  status: ChatToolStatus
  input: Record<string, unknown>
  output: Record<string, unknown>
  assistant_action_id?: number | null
  source_item_id?: number | null
  error?: string | null
  created_at?: string
  updated_at?: string
}

export interface ChatMessage {
  id: number
  conversation_id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  status: 'pending' | 'complete' | 'error'
  metadata?: Record<string, unknown>
  created_at?: string
  tool_calls?: ChatToolCall[]
}

export interface ChatConversation {
  id: number
  title: string
  status: 'active' | 'archived' | 'deleted'
  last_message_at?: string | null
  created_at?: string
  updated_at?: string
}

export interface ChatMessagesResponse {
  conversation: ChatConversation
  messages: ChatMessage[]
}

export interface ChatPostResponse {
  conversation: ChatConversation
  user_message: ChatMessage
  assistant_message: ChatMessage
}

/** What a message may be about: the email the user opened it from. */
export interface ChatMessageBody {
  content: string
  email_id?: string
  thread_id?: string
  provider?: string
  source_item_id?: number
}

export const fetchChatConversations = (limit = 50) =>
  getJson<{ conversations: ChatConversation[] }>('/chat/conversations', { params: { limit } })
    .then(data => data.conversations ?? [])

export const createChatConversation = (title?: string) =>
  postJson<{ conversation: ChatConversation }>('/chat/conversations', { title: title ?? null, project_id: null })
    .then(data => data.conversation)

export const fetchChatMessages = (conversationId: number) =>
  getJson<ChatMessagesResponse>(`/chat/conversations/${conversationId}/messages`)

/** Blocking send. Bounded like Scriba's own client so a hung backend becomes an error. */
export const postChatMessage = (conversationId: number, body: ChatMessageBody) =>
  postJson<ChatPostResponse>(`/chat/conversations/${conversationId}/messages`, body, { timeout: 60_000 })

/** The stored truth about one action card. Reading it never starts an action. */
export const fetchChatToolCall = (toolCallId: number) =>
  getJson<{ tool_call?: ChatToolCall } & Partial<ChatToolCall>>(`/chat/tool-calls/${toolCallId}`)
    .then(data => (data.tool_call ?? data) as ChatToolCall)

/**
 * Approve one action. The idempotency key is derived from the card, as in Scriba's own client,
 * so a repeated click or a repeated request cannot run the action twice.
 */
export const approveChatToolCall = (toolCallId: number, payloadOverrides?: Record<string, unknown>) =>
  postJson<{ tool_call: ChatToolCall }>(`/chat/tool-calls/${toolCallId}/approve`, {
    ...(payloadOverrides ? { payload_overrides: payloadOverrides } : {}),
    idempotency_key: `chat-tc-${toolCallId}`,
  })

export const cancelChatToolCall = (toolCallId: number) =>
  postJson<{ tool_call: ChatToolCall }>(`/chat/tool-calls/${toolCallId}/cancel`)

/**
 * Retry a FAILED action. On Scriba this executes at once: it does not put the card back in
 * front of the user for a second approval (app/chat_service.py retry_tool_call). The UI must
 * say so before the click; see ToolCallCard.
 */
export const retryChatToolCall = (toolCallId: number) =>
  postJson<{ tool_call: ChatToolCall }>(`/chat/tool-calls/${toolCallId}/retry`)

export interface ChatStreamHandlers {
  /** The HTTP stream connected: the server will store the user message. */
  onOpen?: () => void
  onStart?: (userMessage: ChatMessage) => void
  onDelta?: (text: string) => void
  /** The server is replacing what it streamed so far; the answer follows as deltas. */
  onReset?: () => void
  onDone?: (data: ChatPostResponse) => void
  onError?: (message: string) => void
  /** No bytes arrived for STREAM_IDLE_MS. */
  onTimeout?: () => void
}

const STREAM_IDLE_MS = 60_000

/**
 * Streaming send. Transferred from Scriba (postChatMessageStream and consumeChatStream in
 * Gmail/frontend/src/api/index.ts @ 3ae3a2aa); only the types' location changed.
 * Throws when the stream cannot be established, so the caller can fall back to the blocking
 * send. Once onOpen has fired the server has the message: on a later drop, re-read the
 * conversation, never send again.
 */
export async function postChatMessageStream(
  conversationId: number,
  body: ChatMessageBody,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  const resp = await fetch(backendUrl(`/chat/conversations/${conversationId}/messages/stream`), {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(body),
    signal,
  })
  await consumeChatStream(resp, handlers, signal)
}

export class ChatStreamHttpError extends Error {
  constructor(readonly status: number) {
    super(`Chat stream failed (${status})`)
    this.name = 'ChatStreamHttpError'
  }
}

export async function consumeChatStream(
  resp: Response,
  handlers: ChatStreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  if (!resp.ok || !resp.body) throw new ChatStreamHttpError(resp.status)
  handlers.onOpen?.()

  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  const flush = () => {
    let idx: number
    while ((idx = buffer.indexOf('\n\n')) !== -1) {
      const block = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      const dataLines = block.split('\n').filter(l => l.startsWith('data:')).map(l => l.replace(/^data:\s?/, ''))
      if (dataLines.length === 0) continue
      const raw = dataLines.join('\n').trim()
      if (!raw) continue
      let evt: { type?: string; text?: string; message?: string; user_message?: unknown } & Record<string, unknown>
      try { evt = JSON.parse(raw) } catch { continue }
      if (evt.type === 'start') handlers.onStart?.(evt.user_message as ChatMessage)
      else if (evt.type === 'delta') handlers.onDelta?.(String(evt.text ?? ''))
      else if (evt.type === 'reset') handlers.onReset?.()
      else if (evt.type === 'done') handlers.onDone?.(evt as unknown as ChatPostResponse)
      else if (evt.type === 'error') handlers.onError?.(String(evt.message ?? 'Something went wrong.'))
    }
  }
  try {
    for (;;) {
      let timer: ReturnType<typeof setTimeout> | undefined
      const idle = new Promise<'timeout'>(resolve => {
        timer = setTimeout(() => resolve('timeout'), STREAM_IDLE_MS)
      })
      const result = await Promise.race([reader.read(), idle])
      if (timer !== undefined) clearTimeout(timer)
      if (result === 'timeout') {
        try { await reader.cancel() } catch { /* already closing */ }
        handlers.onTimeout?.()
        return
      }
      const { value, done } = result
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      flush()
    }
    buffer += decoder.decode()
    flush()
  } catch (err) {
    if ((err as { name?: string })?.name === 'AbortError' || signal?.aborted) return
    throw err
  }
}

// ── Tasks, reminders, notifications ─────────────────────────────────────────

export interface ScribaTask {
  id: string | number
  source_item_id?: string | number | null
  source_item_type?: string | null
  source_item_platform?: string | null
  source_item_title?: string | null
  title?: string
  description?: string
  status?: string
  priority?: string
  effective_priority?: string
  due_at?: string
  created_at?: string
  updated_at?: string
}

export const fetchTasks = (limit = 200) =>
  getJson<{ tasks: ScribaTask[]; truncated?: boolean }>('/tasks', { params: { limit, order: 'actionable' } })

export const completeTask = (taskId: string | number) =>
  postJson<{ task: ScribaTask }>(`/tasks/${taskId}/complete`).then(data => data.task)

export interface ScribaReminder {
  id?: string | number
  title?: string
  reminder_type?: string
  remind_at?: string
  status?: string
  message?: string
  linked_task_id?: string | number
  linked_source_item_id?: string | number
}

export const fetchReminders = () =>
  getJson<{ reminders: ScribaReminder[] }>('/reminders/upcoming').then(data => data.reminders ?? [])

/** Take back a scheduled reminder before it fires (404 once sent or cancelled). */
export const cancelReminder = (reminderId: string | number) =>
  postJson<{ reminder: ScribaReminder }>(`/reminders/${reminderId}/cancel`).then(data => data.reminder)

export interface ScribaNotification {
  id: number
  notification_type: string
  title?: string
  body?: string
  status?: 'unread' | 'read' | 'dismissed' | 'snoozed'
  provider?: string
  created_at?: string
}

export const fetchNotifications = (limit = 30) =>
  getJson<{ notifications: ScribaNotification[]; summary?: { unread_count?: number } }>('/notifications', { params: { limit } })

// ── Reply drafts ────────────────────────────────────────────────────────────

export interface ScribaDraft {
  id: string | number
  provider_account_id?: string | null
  account_email?: string | null
  email_id?: string
  thread_id?: string
  subject: string
  from_addr: string
  status?: string
  provider?: string
  draft_text?: string
  final_text?: string
  calendar_context?: {
    action?: string
    suggested_slots?: { start?: string; end?: string; label?: string }[]
  }
}

export const fetchDrafts = () =>
  getJson<{ drafts: ScribaDraft[] }>('/drafts').then(data => data.drafts ?? [])

/**
 * Ask Scriba to write a reply draft. The body is the one the Desk overlay prepared in
 * `draftRequest` (GET /desk/inbox/item): for a meeting request its user_context lists only
 * times verified free on every connected calendar. The draft is stored in Scriba for review.
 * Nothing is sent. This needs a model on the backend.
 */
export const createDraftFromRequest = (request: DraftRequest) =>
  postJson<{ draft: ScribaDraft }>(request.path, request.body, { timeout: 90_000 }).then(data => data.draft)

/** Discard a stored draft. Nothing was sent, so nothing is recalled. */
export const discardDraft = (draftId: string | number) => postJson(`/drafts/${draftId}/discard`)

// POST /drafts/{id}/send exists in Scriba and is deliberately not exposed here: the Desk does
// not send mail until the backend reports that external writes are verified (writePolicy.ts).
