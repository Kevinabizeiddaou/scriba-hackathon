/**
 * The secretary's work queue: every action the agent has proposed or run, in one list.
 *
 * Scriba records an action as a chat tool call with a server-side status. The Desk reads those
 * records and shows them; it never advances a status itself. There is no endpoint that lists
 * actions across conversations yet, so the queue is built by reading the most recent
 * conversations (see RECENT_CONVERSATIONS). The backend requirement for a direct listing is in
 * docs/frontend/LIVE_INTEGRATION.md.
 *
 * Work stages. The product's target pipeline is
 *   Received -> Classified -> Planning -> Awaiting approval -> Executing -> Verifying ->
 *   Completed / Awaiting reply / Escalated / Failed.
 * Only the stages the current backend actually reports are shown (WORK_STAGES[..].supported).
 * A stage the backend cannot report is listed here with the reason and is not rendered as if it
 * were live.
 */
import type { ChatConversation, ChatMessage, ChatToolCall, ChatToolStatus } from './scribaApi'
import { fetchChatConversations, fetchChatMessages } from './scribaApi'
import { toolEffect, type ToolEffect } from './writePolicy'

export type WorkStage =
  | 'received'
  | 'classified'
  | 'planning'
  | 'needs_info'
  | 'awaiting_approval'
  | 'executing'
  | 'verifying'
  | 'completed'
  | 'partially_completed'
  | 'awaiting_reply'
  | 'escalated'
  | 'failed'
  | 'cancelled'
  | 'unsupported'

export interface WorkStageInfo {
  label: string
  tone: 'neutral' | 'ok' | 'warn' | 'danger' | 'info' | 'accent'
  /** True when the current backend reports this stage. */
  supported: boolean
  /** Where the stage comes from, or why it cannot be shown yet. */
  source: string
}

export const WORK_STAGES: Record<WorkStage, WorkStageInfo> = {
  received: { label: 'Received', tone: 'neutral', supported: false, source: 'Mail is triaged in the same read that returns it, so a message is never seen as received but unclassified.' },
  classified: { label: 'Classified', tone: 'accent', supported: true, source: 'GET /desk/inbox: every message carries a rule-based triage result.' },
  planning: { label: 'Planning', tone: 'info', supported: true, source: 'Chat action status pending or draft.' },
  needs_info: { label: 'Needs information', tone: 'warn', supported: true, source: 'Chat action status needs_info: the agent or a safety check is waiting for the user.' },
  awaiting_approval: { label: 'Awaiting approval', tone: 'warn', supported: true, source: 'Chat action status awaiting_approval.' },
  executing: { label: 'Executing', tone: 'info', supported: true, source: 'Chat action status approved or executing.' },
  verifying: { label: 'Verifying', tone: 'info', supported: false, source: 'The backend does not report a separate verification step; an action goes from executing to its result.' },
  completed: { label: 'Completed', tone: 'ok', supported: true, source: 'Chat action status executed, with the provider result on the card.' },
  partially_completed: { label: 'Partly completed', tone: 'danger', supported: true, source: 'Chat action status partially_executed: some parts ran and some did not.' },
  awaiting_reply: { label: 'Awaiting reply', tone: 'info', supported: false, source: 'Scriba does not track sent mail that is waiting for an answer.' },
  escalated: { label: 'Escalated', tone: 'danger', supported: false, source: 'The backend has no escalation record.' },
  failed: { label: 'Failed', tone: 'danger', supported: true, source: 'Chat action status failed.' },
  cancelled: { label: 'Cancelled', tone: 'neutral', supported: true, source: 'Chat action status cancelled.' },
  unsupported: { label: 'Not supported', tone: 'neutral', supported: true, source: 'Chat action status unsupported.' },
}

const STAGE_OF_STATUS: Record<ChatToolStatus, WorkStage> = {
  pending: 'planning',
  draft: 'planning',
  needs_info: 'needs_info',
  awaiting_approval: 'awaiting_approval',
  approved: 'executing',
  executing: 'executing',
  executed: 'completed',
  partially_executed: 'partially_completed',
  failed: 'failed',
  cancelled: 'cancelled',
  unsupported: 'unsupported',
}

/** An unknown status is never guessed into a stage: it is shown as planning with its raw value. */
export function stageOf(status: string): WorkStage {
  return STAGE_OF_STATUS[status as ChatToolStatus] ?? 'planning'
}

export const IN_FLIGHT: ReadonlySet<ChatToolStatus> = new Set(['approved', 'executing'])

/** The user has to do something before this action can move. */
export function needsUser(card: ActionCard): boolean {
  const stage = stageOf(card.toolCall.status)
  return stage === 'awaiting_approval' || stage === 'needs_info'
}

/** It did not end cleanly: a person should look at it. */
export function needsIntervention(card: ActionCard): boolean {
  const stage = stageOf(card.toolCall.status)
  return stage === 'failed' || stage === 'partially_completed'
}

export interface ActionCard {
  toolCall: ChatToolCall
  effect: ToolEffect
  conversation: Pick<ChatConversation, 'id' | 'title'>
  /** What the assistant said when it proposed this: the nearest thing the backend has to a reason. */
  assistantText: string
  /** The user's message that led to it, when it is in the same conversation. */
  requestText: string | null
}

export function cardsOfConversation(conversation: Pick<ChatConversation, 'id' | 'title'>, messages: ChatMessage[]): ActionCard[] {
  const cards: ActionCard[] = []
  let lastUser: string | null = null
  for (const message of messages) {
    if (message.role === 'user') {
      lastUser = message.content
      continue
    }
    for (const toolCall of message.tool_calls ?? []) {
      cards.push({ toolCall, effect: toolEffect(toolCall.tool_name), conversation, assistantText: message.content, requestText: lastUser })
    }
  }
  return cards
}

/** How many of the most recent conversations the queue reads. Older actions are not listed. */
export const RECENT_CONVERSATIONS = 12

export interface WorkQueue {
  cards: ActionCard[]
  /** Conversations that could not be read. Their actions are missing from `cards`. */
  failedConversations: number
  /** True when there are more conversations than the queue read. */
  truncated: boolean
}

export async function loadWorkQueue(): Promise<WorkQueue> {
  const conversations = await fetchChatConversations(50)
  const recent = conversations.slice(0, RECENT_CONVERSATIONS)
  const results = await Promise.allSettled(recent.map(conversation => fetchChatMessages(conversation.id)))
  const cards: ActionCard[] = []
  let failedConversations = 0
  results.forEach((result, index) => {
    if (result.status === 'rejected') {
      failedConversations += 1
      return
    }
    cards.push(...cardsOfConversation(recent[index], result.value.messages ?? []))
  })
  // A failure to read anything at all is an error, not an empty queue.
  if (recent.length > 0 && failedConversations === recent.length) {
    const first = results[0] as PromiseRejectedResult
    throw first.reason instanceof Error ? first.reason : new Error(String(first.reason))
  }
  cards.sort((a, b) => Date.parse(b.toolCall.updated_at ?? b.toolCall.created_at ?? '') - Date.parse(a.toolCall.updated_at ?? a.toolCall.created_at ?? '') || b.toolCall.id - a.toolCall.id)
  return { cards, failedConversations, truncated: conversations.length > recent.length }
}

/** Only actions that change something are work items; reads are answers, shown in chat. */
export function isWorkItem(card: ActionCard): boolean {
  return card.effect !== 'read'
}

export const WORK_QUEUE_KEY = ['desk', 'work-queue'] as const

/** Poll quickly while something is executing, slowly otherwise. */
export function workQueueRefetchInterval(queue: WorkQueue | undefined): number {
  return queue?.cards.some(card => IN_FLIGHT.has(card.toolCall.status)) ? 2_500 : 30_000
}
