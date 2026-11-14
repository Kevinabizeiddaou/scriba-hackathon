import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { DeskInbox, DeskRun, DeskSweep, TriagedEmail } from '../api/desk'

vi.mock('../api/desk', async importOriginal => ({
  ...(await importOriginal<typeof import('../api/desk')>()),
  fetchDeskRuns: vi.fn(),
  fetchDeskRun: vi.fn(),
}))

import { fetchDeskRun, fetchDeskRuns } from '../api/desk'
import {
  INTAKE_CATEGORIES,
  QUEUE_GROUPS,
  QUEUE_ORDER,
  RUN_DETAIL_LIMIT,
  groupOf,
  loadRunQueue,
  nextStepOf,
  partialBreakdown,
  runHeadline,
  runQueueRefetchInterval,
  sweepGaps,
  sweepLines,
  timelineOf,
  toRunRow,
  unstartedMail,
} from './deskRuns'
import { deskAction as action, deskRun as run, executedAction as executed } from '../test/deskFixtures'

describe('where a run sits in the queue', () => {
  it('puts a run with an approvable action under approval, and one whose cards are all held under input', () => {
    expect(groupOf(run())).toBe('decision')
    expect(groupOf(run({ actions: [action({ status: 'needs_info' })] }))).toBe('input')
    expect(groupOf(run({ actions: [action({ status: 'needs_info' }), action({ toolCallId: 32, status: 'awaiting_approval' })] }))).toBe('decision')
  })

  it('treats a held meeting request and an unwritten reply as needing the person, not as nothing to do', () => {
    const held = run({ state: 'no_action_proposed', category: 'meeting_request', actions: [], held: { reason: 'calendar_conflict', message: 'Taken.', slots: [], calendars: [] } })
    expect(groupOf(held)).toBe('input')
    expect(groupOf(run({ state: 'no_action_proposed', category: 'needs_reply', actions: [], next: ['draft_reply'] }))).toBe('input')
    expect(groupOf(run({ state: 'no_action_proposed', category: 'informational', actions: [] }))).toBe('no_action')
  })

  it('keeps a completed run open while its confirmation reply has not been proposed', () => {
    const booked = run({ state: 'completed', category: 'meeting_request', actions: [executed({ tool_name: 'create_calendar_event' })], next: ['advance'] })
    expect(groupOf(booked)).toBe('input')
    expect(nextStepOf(booked).kind).toBe('advance')
    expect(groupOf({ ...booked, next: [] })).toBe('done')
  })

  it('never shows a partly executed action as finished work, even when the run says completed', () => {
    // workflow._DONE counts partially_executed as done, so the run state alone is not enough.
    const partly = run({ state: 'completed', actions: [action({ status: 'partially_executed', approve: null, assistantActionId: 91, verified: true })] })
    expect(groupOf(partly)).toBe('problem')
    expect(nextStepOf(partly).kind).toBe('inspect_failure')
    expect(timelineOf(partly).find(step => step.id === 'execution')!.state).toBe('failed')
  })

  it('maps failed, partial, executing and cancelled runs', () => {
    expect(groupOf(run({ state: 'failed', actions: [action({ status: 'failed', approve: null })] }))).toBe('problem')
    expect(groupOf(run({ state: 'partial' }))).toBe('problem')
    expect(groupOf(run({ state: 'executing', actions: [action({ status: 'executing', approve: null })] }))).toBe('in_progress')
    expect(groupOf(run({ state: 'cancelled', actions: [action({ status: 'cancelled', approve: null })] }))).toBe('cancelled')
  })

  it('does not guess at a state it does not know', () => {
    const odd = run({ state: 'awaiting_reply' as DeskRun['state'] })
    expect(groupOf(odd)).toBe('unknown')
    expect(nextStepOf(odd)).toMatchObject({ kind: 'unknown', label: 'The backend reports "awaiting_reply"' })
  })

  it('lists every group once, with what needs the person before finished work', () => {
    expect([...QUEUE_ORDER].sort()).toEqual(Object.keys(QUEUE_GROUPS).sort())
    expect(QUEUE_ORDER.indexOf('decision')).toBeLessThan(QUEUE_ORDER.indexOf('done'))
    expect(QUEUE_ORDER.indexOf('problem')).toBeLessThan(QUEUE_ORDER.indexOf('in_progress'))
  })
})

describe('the next step', () => {
  it('says what a held meeting request needs, by reason', () => {
    const held = (reason: NonNullable<DeskRun['held']>['reason']) => nextStepOf(run({ state: 'no_action_proposed', category: 'meeting_request', actions: [], held: { reason, message: 'x', slots: [], calendars: [] } }))
    expect(held('availability_unknown')).toMatchObject({ kind: 'held', detail: expect.stringContaining('never treated as free') })
    expect(held('change_request').detail).toContain('not proposed automatically yet')
    expect(held('time_not_understood').label).toBe('No specific time could be read from the message')
  })

  it('does not call an executed action verified unless the backend says so', () => {
    const recorded = run({ state: 'completed', actions: [executed()] })
    expect(nextStepOf(recorded)).toMatchObject({ kind: 'none', detail: 'Every action ran and Scriba recorded it.' })
    const unrecorded = run({ state: 'completed', actions: [executed({ assistantActionId: null, verified: false })] })
    expect(nextStepOf(unrecorded).kind).toBe('check_result')
    expect(timelineOf(unrecorded).find(step => step.id === 'verified')).toMatchObject({ state: 'held', detail: expect.stringContaining('no record in Scriba') })
  })

  it('warns that a retry runs at once', () => {
    expect(nextStepOf(run({ state: 'failed', actions: [action({ status: 'failed', approve: null })] })).detail).toContain('runs immediately, without a second approval')
  })
})

describe('the timeline of a run', () => {
  it('shows only reported stages: no calendar step for a task, and nothing after "proposed" when nothing was proposed', () => {
    expect(timelineOf(run()).map(step => [step.id, step.state])).toEqual([
      ['received', 'done'],
      ['classified', 'done'],
      ['proposed', 'done'],
      ['approval', 'current'],
      ['execution', 'upcoming'],
      ['verified', 'upcoming'],
    ])
    const info = run({ state: 'no_action_proposed', category: 'informational', actions: [] })
    expect(timelineOf(info).map(step => [step.id, step.state])).toEqual([['received', 'done'], ['classified', 'done'], ['proposed', 'not_needed']])
  })

  it('marks the calendar step as held when a calendar could not be read, and says unknown is not free', () => {
    const held = run({
      state: 'no_action_proposed',
      category: 'meeting_request',
      actions: [],
      held: {
        reason: 'availability_unknown',
        message: 'A calendar could not be read, so the requested time is not verified. No event is proposed.',
        slots: [],
        calendars: [
          { provider: 'google', account: 'exec@example.test', ok: true, error: null, busy_count: 3 },
          { provider: 'outlook', account: 'exec@contoso.example', ok: false, error: 'reconnect_required', busy_count: 0 },
        ],
      },
    })
    const steps = timelineOf(held)
    expect(steps.find(step => step.id === 'context')).toMatchObject({ state: 'held', detail: '1 of 2 calendars could not be read. An unread calendar is unknown, not free.' })
    expect(steps.at(-1)).toMatchObject({ id: 'proposed', state: 'held', label: 'Nothing proposed' })
  })

  it('follows a meeting through approval, execution and the record Scriba keeps', () => {
    const availability = { free: true, calendars: [{ provider: 'google' as const, account: 'exec@example.test', ok: true, error: null, busy_count: 2 }] }
    const waiting = run({ category: 'meeting_request', actions: [action({ tool_name: 'create_calendar_event', availability })] })
    expect(timelineOf(waiting).map(step => step.state)).toEqual(['done', 'done', 'done', 'done', 'current', 'upcoming', 'upcoming'])
    const done = run({ state: 'completed', category: 'meeting_request', actions: [executed({ tool_name: 'create_calendar_event', availability, assistantActionId: 412 })], next: ['advance'] })
    expect(timelineOf(done).at(-1)).toMatchObject({ id: 'verified', state: 'done', detail: 'Scriba recorded the action (#412).' })
  })

  it('separates what ran, what failed and what was never attempted', () => {
    const partial = run({
      state: 'partial',
      category: 'meeting_request',
      actions: [executed({ toolCallId: 1, tool_name: 'create_calendar_event' }), action({ toolCallId: 2, tool_name: 'send_email', status: 'failed', approve: null, error: 'provider_error' }), action({ toolCallId: 3, tool_name: 'create_task' })],
    })
    const { ran, failed, notRun } = partialBreakdown(partial)
    expect([ran.map(a => a.toolCallId), failed.map(a => a.toolCallId), notRun.map(a => a.toolCallId)]).toEqual([[1], [2], [3]])
    expect(timelineOf(partial).find(step => step.id === 'execution')).toMatchObject({ state: 'failed', detail: '1 ran, 1 did not finish, 1 not run.' })
    expect(runHeadline(partial)).toBe('Create a calendar event, then Send an email, then Record a task')
  })

  it('does not count cancelled cards as work that ran', () => {
    const cancelled = run({ state: 'cancelled', actions: [action({ status: 'cancelled', approve: null })] })
    expect(timelineOf(cancelled).slice(-3).map(step => step.state)).toEqual(['not_needed', 'not_needed', 'not_needed'])
  })
})

describe('reading the queue', () => {
  beforeEach(() => {
    vi.mocked(fetchDeskRuns).mockReset()
    vi.mocked(fetchDeskRun).mockReset()
  })
  const rows = (n: number) => Array.from({ length: n }, (_, i) => ({ runId: 100 - i, provider: 'gmail', email_id: `m-${i}`, subject: `Subject ${i}`, from_addr: 'a@example.test', category: 'action_item', created_at: '2026-11-14T08:00:00+00:00' }))

  it('reads the newest runs in full, bounded, and says how many it did not read', async () => {
    vi.mocked(fetchDeskRuns).mockResolvedValue({ account: 'exec@example.test', runs: rows(RUN_DETAIL_LIMIT + 5) } as never)
    let inFlight = 0
    let peak = 0
    vi.mocked(fetchDeskRun).mockImplementation(async runId => {
      inFlight += 1
      peak = Math.max(peak, inFlight)
      await new Promise(resolve => setTimeout(resolve, 2))
      inFlight -= 1
      return run({ runId })
    })
    const queue = await loadRunQueue()
    expect(fetchDeskRun).toHaveBeenCalledTimes(RUN_DETAIL_LIMIT)
    expect(peak).toBeLessThanOrEqual(4) // never a burst of requests at a slow backend
    expect(queue).toMatchObject({ listed: RUN_DETAIL_LIMIT + 5, notRead: 5, failedReads: 0 })
    expect(queue.entries[0]).toMatchObject({ row: { runId: 100, emailId: 'm-0', fromAddr: 'a@example.test' }, run: { runId: 100 } })
    expect(queue.entries.at(-1)).toMatchObject({ run: null, error: null })
  })

  it('reports a run it could not read as unknown, and fails outright when none could be read', async () => {
    vi.mocked(fetchDeskRuns).mockResolvedValue({ account: 'x', runs: rows(2) } as never)
    vi.mocked(fetchDeskRun).mockImplementation(async runId => {
      if (runId === 100) throw new Error('Request timed out')
      return run({ runId })
    })
    const queue = await loadRunQueue()
    expect(queue.failedReads).toBe(1)
    expect(queue.entries[0]).toMatchObject({ run: null, error: 'Request timed out' })

    vi.mocked(fetchDeskRun).mockRejectedValue(new Error('Backend unreachable'))
    await expect(loadRunQueue()).rejects.toThrow('Backend unreachable')
  })

  it('answers an empty list with an empty queue and no detail reads', async () => {
    vi.mocked(fetchDeskRuns).mockResolvedValue({ account: 'x', runs: [] } as never)
    expect(await loadRunQueue()).toEqual({ entries: [], listed: 0, notRead: 0, failedReads: 0 })
    expect(fetchDeskRun).not.toHaveBeenCalled()
  })

  it('polls only while something is executing', () => {
    const entry = (state: DeskRun['state']) => ({ row: toRunRow({ runId: 1 })!, run: run({ state }), error: null })
    expect(runQueueRefetchInterval({ entries: [entry('executing')], listed: 1, notRead: 0, failedReads: 0 })).toBe(4_000)
    expect(runQueueRefetchInterval({ entries: [entry('awaiting_approval')], listed: 1, notRead: 0, failedReads: 0 })).toBe(false)
    expect(runQueueRefetchInterval(undefined)).toBe(false)
  })

  it('drops a row without a run id instead of inventing one', () => {
    expect(toRunRow({ subject: 'No id' })).toBeNull()
    expect(toRunRow({ runId: 4, provider: 'slack' })).toMatchObject({ runId: 4, provider: null })
  })
})

describe('mail with no run yet', () => {
  const mail = (id: string, category: TriagedEmail['triage']['category'], provider: 'gmail' | 'outlook' = 'gmail') =>
    ({ id, provider, subject: id, triage: { category, outcome: 'none', priority: 'normal', needs_reply: false, has_deadline: false, reasons: [] } }) as unknown as TriagedEmail
  const inbox = { items: [mail('a', 'action_item'), mail('b', 'informational'), mail('c', 'meeting_request'), mail('d', 'needs_reply', 'outlook'), mail('e', 'automated')] } as DeskInbox

  it('lists only messages a sweep would open a run for, minus those that already have one', () => {
    const rows = [toRunRow({ runId: 1, provider: 'gmail', email_id: 'c' })!, toRunRow({ runId: 2, provider: 'gmail', email_id: 'd' })!]
    // "d" is an Outlook message; a Gmail run with the same id is a different message.
    expect(unstartedMail(inbox, rows).map(item => item.id)).toEqual(['a', 'd'])
    expect(unstartedMail(undefined, rows)).toEqual([])
  })
})

describe('what a check for new work did', () => {
  const sweep = (over: Partial<DeskSweep> = {}): DeskSweep => ({
    account: 'exec@example.test',
    status: 'completed',
    examined: 25,
    opened: [{ provider: 'gmail', id: 'a', subject: 'A', category: 'action_item', runId: 12, state: 'awaiting_approval' }],
    existing: 4,
    skipped: 17,
    deferred: [{ provider: 'gmail', id: 'z', subject: 'Z', category: 'needs_reply' }, { provider: 'outlook', id: 'y', subject: 'Y', category: 'meeting_request' }],
    failed: [{ provider: 'gmail', id: 'f', subject: 'F', category: 'meeting_request', error: 'TimeoutError' }],
    sources: [{ provider: 'gmail', state: 'connected', ok: true, error: null, count: 25, hasMore: true }],
    complete: true,
    ...over,
  })

  it('accounts for every examined message', () => {
    const lines = sweepLines(sweep())
    expect(lines.map(line => [line.id, line.count])).toEqual([['examined', 25], ['opened', 1], ['existing', 4], ['skipped', 17], ['deferred', 2], ['failed', 1]])
    const counted = lines.filter(line => line.id !== 'examined').reduce((sum, line) => sum + line.count, 0)
    expect(counted).toBe(25)
    expect(lines.find(line => line.id === 'opened')!.note).toContain('Nothing was sent or written')
  })

  it('names the mailbox that could not be read, and does not blame one that is simply not connected', () => {
    expect(sweepGaps(sweep())).toEqual([])
    const gaps = sweepGaps(
      sweep({
        complete: false,
        sources: [
          { provider: 'gmail', state: 'connected', ok: true, error: null, count: 10, hasMore: false },
          { provider: 'outlook', state: 'connected', ok: false, error: 'provider_error', count: 0, hasMore: false },
        ],
      }),
    )
    expect(gaps).toEqual(['Outlook could not be read (provider_error), so its mail was not examined.'])
    expect(sweepGaps(sweep({ complete: false, sources: [] }))).toHaveLength(1)
  })
})

/**
 * Compatibility with the backend, checked against its source rather than against a copy of what
 * we think it returns. If backend/desk_overlay/workflow.py stops emitting a field this file reads,
 * or changes the set of states and categories, these fail.
 */
describe('compatibility with backend/desk_overlay/workflow.py', () => {
  const source = readFileSync(resolve(__dirname, '../../../backend/desk_overlay/workflow.py'), 'utf8')
  const tuple = (name: string) => [...source.match(new RegExp(`${name} = \\(([^)]*)\\)`))![1].matchAll(/"([a-z_]+)"/g)].map(match => match[1])

  it('reads only list fields the backend emits', () => {
    const listRuns = source.slice(source.indexOf('def list_runs'), source.indexOf('def _reply_subject'))
    for (const key of ['runId', 'provider', 'email_id', 'subject', 'from_addr', 'category', 'created_at']) expect(listRuns, key).toContain(`"${key}"`)
    // The list carries no state: the reason the queue reads each run. Remove the detail reads when this fails.
    expect(listRuns).not.toContain('"state"')
  })

  it('knows every run state and every field of the run view', () => {
    const view = source.slice(source.indexOf('    def view('), source.indexOf('    def list_runs'))
    const states = [...view.matchAll(/state = "([a-z_]+)"/g), ...view.matchAll(/"(awaiting_approval|executing)" if/g), ...view.matchAll(/else "([a-z_]+)"/g)].map(match => match[1])
    expect([...new Set(states)].sort()).toEqual(['awaiting_approval', 'cancelled', 'completed', 'executing', 'failed', 'no_action_proposed', 'partial'])
    for (const key of ['runId', 'duplicate', 'state', 'email', 'category', 'outcome', 'createdAt', 'held', 'draftRequest', 'actions', 'next']) expect(view, key).toContain(`"${key}"`)
    for (const step of ['advance', 'draft_reply']) expect(view).toContain(`next_steps.append("${step}")`)
  })

  it('agrees on which mail a sweep takes and on what counts as done', () => {
    expect(tuple('SWEEP_CATEGORIES')).toEqual([...INTAKE_CATEGORIES])
    // The backend treats partially_executed as done. The Desk does not show it as finished (groupOf).
    expect(tuple('_DONE')).toEqual(['executed', 'partially_executed'])
  })

  it('knows every reason a meeting request can be held for', () => {
    const reasons = new Set([...[...source.matchAll(/"reason": "([a-z_]+)"/g)].map(match => match[1]), 'calendar_conflict', 'availability_unknown'])
    expect(reasons.size).toBeGreaterThanOrEqual(5)
    for (const reason of reasons) {
      const held = { reason, message: 'x', slots: [], calendars: [] } as NonNullable<DeskRun['held']>
      expect(nextStepOf(run({ state: 'no_action_proposed', actions: [], held })).label, reason).not.toBe('The meeting request is held')
    }
    expect(source).toContain('"calendar_conflict" if check["free"] is False else "availability_unknown"')
  })

  it('reads only action fields the backend emits', () => {
    const actionView = source.slice(source.indexOf('def _action_view'))
    for (const key of ['toolCallId', 'tool_name', 'status', 'requiresApproval', 'input', 'message', 'error', 'availability', 'assistantActionId', 'verified', 'approve']) expect(actionView, key).toContain(`"${key}"`)
  })
})
