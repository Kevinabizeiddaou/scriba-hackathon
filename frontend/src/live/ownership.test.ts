/**
 * Whose work an action card is: the Desk secretary's (its conversation is a Desk run, or a run
 * lists its tool call) or Scriba's own chat. Without the run list nothing is assumed.
 */
import { describe, expect, it } from 'vitest'
import { deskAction, deskRun } from '../test/deskFixtures'
import { toRunRow, type RunQueue } from './deskRuns'
import { deskIndexOf, deskLinkOf, partitionCards } from './ownership'
import type { ChatToolCall } from './scribaApi'
import type { ActionCard } from './workQueue'

const card = (id: number, conversationId: number, over: Partial<ChatToolCall> = {}, title = 'Monday planning'): ActionCard => ({
  toolCall: { id, message_id: id * 10, conversation_id: conversationId, tool_name: 'create_task', status: 'awaiting_approval', input: {}, output: {}, ...over },
  effect: 'internal_write',
  conversation: { id: conversationId, title },
  assistantText: '',
  requestText: null,
})

/** Run 7 was read in full and lists actions 31 and 32. Run 8 is listed, but its detail was not read. */
const run7 = deskRun({ runId: 7, actions: [deskAction({ toolCallId: 31 }), deskAction({ toolCallId: 32, tool_name: 'send_email' })] })
const queue: RunQueue = {
  entries: [
    { row: toRunRow({ runId: 7, subject: 'Subject on the row' })!, run: run7, error: null },
    { row: toRunRow({ runId: 8, subject: 'Offsite dates' })!, run: null, error: 'Request timed out' },
  ],
  listed: 2,
  notRead: 0,
  failedReads: 1,
}

describe('the index of Desk-owned work', () => {
  it('is null without the run list: ownership is unknown, not empty', () => {
    expect(deskIndexOf(undefined)).toBeNull()
  })

  it('holds every listed run id, and each action of the runs that were read', () => {
    const index = deskIndexOf(queue)!
    expect([...index.runIds].sort()).toEqual([7, 8])
    expect([...index.byToolCall.keys()].sort()).toEqual([31, 32])
    expect(index.byToolCall.get(32)).toMatchObject({ runId: 7, subject: 'Board pack by Thursday' })
    expect(index.byToolCall.get(32)!.action).toBe(run7.actions[1])
    expect(deskIndexOf({ entries: [], listed: 0, notRead: 0, failedReads: 0 })).toMatchObject({ runIds: new Set(), byToolCall: new Map() })
  })

  it('falls back to the subject on the row when the run names none', () => {
    const unnamed = deskRun({ runId: 7, email: { ...run7.email, subject: null as unknown as string } })
    const index = deskIndexOf({ ...queue, entries: [{ row: toRunRow({ runId: 7, subject: 'Subject on the row' })!, run: unnamed, error: null }] })!
    expect(index.byToolCall.get(31)!.subject).toBe('Subject on the row')
  })
})

describe('the Desk run a card belongs to', () => {
  const index = deskIndexOf(queue)

  it("finds it by the card's tool-call id, with the Desk's view of the action", () => {
    // The card sits in another conversation as far as Scriba's record goes; the run lists it, so it is the Desk's.
    const link = deskLinkOf(card(31, 2), index)
    expect(link).toMatchObject({ runId: 7, subject: 'Board pack by Thursday' })
    expect(link!.action).toBe(run7.actions[0])
  })

  it("finds it by the conversation id, which is the run's id, without an action when the run was not read", () => {
    expect(deskLinkOf(card(99, 8, {}, 'Desk: Offsite dates'), index)).toEqual({ runId: 8, subject: 'Desk: Offsite dates', action: null })
    // A run that was read but does not list this card (it was added after the read) still owns it.
    expect(deskLinkOf(card(77, 7, {}, ''), index)).toEqual({ runId: 7, subject: null, action: null })
    // The conversation on the card's own record is used when the tool call does not carry one.
    expect(deskLinkOf(card(98, 8, { conversation_id: undefined as unknown as number }), index)).toMatchObject({ runId: 8 })
  })

  it('is null for a card from Scriba chat, and for any card when the index is unknown', () => {
    expect(deskLinkOf(card(21, 2), index)).toBeNull()
    expect(deskLinkOf(card(31, 7), null)).toBeNull()
  })
})

describe('sorting cards by owner', () => {
  const byTool = card(31, 2)
  const byConversation = card(99, 8)
  const chat = card(21, 2)
  const chatToo = card(22, 3)

  it('puts Desk-owned cards and Scriba-chat cards in separate lists, in the order given', () => {
    const owned = partitionCards([chat, byTool, chatToo, byConversation], deskIndexOf(queue))
    expect(owned.known).toBe(true)
    expect(owned.desk).toEqual([byTool, byConversation])
    expect(owned.scriba).toEqual([chat, chatToo])
  })

  it('claims nothing for the Desk when the run list is not available, and says ownership is not known', () => {
    const owned = partitionCards([chat, byTool, byConversation], deskIndexOf(undefined))
    expect(owned).toEqual({ desk: [], scriba: [chat, byTool, byConversation], known: false })
  })

  it('knows that no card is the Desk\'s when the backend lists no run', () => {
    const owned = partitionCards([chat, byTool], deskIndexOf({ entries: [], listed: 0, notRead: 0, failedReads: 0 }))
    expect(owned).toEqual({ desk: [], scriba: [chat, byTool], known: true })
    expect(partitionCards([], deskIndexOf(queue))).toEqual({ desk: [], scriba: [], known: true })
  })
})
