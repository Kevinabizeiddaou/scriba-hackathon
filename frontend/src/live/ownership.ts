/**
 * Whose work an action card is.
 *
 * Scriba records every proposed action as a chat tool call, whoever proposed it. Two things write
 * them: the Desk secretary, when it opens a run for an incoming message or an instruction, and
 * Scriba's own chat. The approval center and the activity record used to count both as "the
 * secretary's", so cards that have nothing to do with the Desk's work (in a sandbox: Scriba's
 * seeded fixtures) inflated the secretary's numbers.
 *
 * A Desk run IS a Scriba conversation: `runId` is that conversation's id (BACKEND_CONTRACT
 * section 6), and a run lists its own action ids. So a card is Desk-owned when its conversation
 * is a listed run or its id is one of a run's actions. Nothing else is assumed: without the run
 * list, ownership is unknown and the screens say so instead of guessing.
 */
import type { DeskAction } from '../api/desk'
import type { RunQueue } from './deskRuns'
import type { ActionCard } from './workQueue'

export interface DeskLink {
  runId: number
  subject: string | null
  /** The Desk's view of the action. Null when the run was listed but not read in full. */
  action: DeskAction | null
}

/** Each Desk-owned tool call, by id, plus every run's conversation id. */
export interface DeskIndex {
  byToolCall: Map<number, DeskLink>
  runIds: Set<number>
}

export function deskIndexOf(queue: RunQueue | undefined): DeskIndex | null {
  if (!queue) return null
  const byToolCall = new Map<number, DeskLink>()
  const runIds = new Set<number>()
  for (const entry of queue.entries) {
    runIds.add(entry.row.runId)
    for (const action of entry.run?.actions ?? []) byToolCall.set(action.toolCallId, { runId: entry.row.runId, subject: entry.run!.email.subject ?? entry.row.subject, action })
  }
  return { byToolCall, runIds }
}

export function deskLinkOf(card: ActionCard, index: DeskIndex | null): DeskLink | null {
  if (!index) return null
  const direct = index.byToolCall.get(card.toolCall.id)
  if (direct) return direct
  const conversation = card.toolCall.conversation_id ?? card.conversation.id
  return index.runIds.has(conversation) ? { runId: conversation, subject: card.conversation.title || null, action: null } : null
}

export interface Ownership {
  /** Proposed by the Desk secretary for a run. */
  desk: ActionCard[]
  /** Proposed in Scriba's chat, or already in Scriba's records. Not the Desk secretary's work. */
  scriba: ActionCard[]
  /** False when the run list is not available: every card is then in `scriba`, and that is not a finding. */
  known: boolean
}

export function partitionCards(cards: ActionCard[], index: DeskIndex | null): Ownership {
  if (!index) return { desk: [], scriba: cards, known: false }
  const desk: ActionCard[] = []
  const scriba: ActionCard[] = []
  for (const card of cards) (deskLinkOf(card, index) ? desk : scriba).push(card)
  return { desk, scriba, known: true }
}
