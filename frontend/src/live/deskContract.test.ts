/**
 * The newer backend fields the screens read as untyped data: each is checked field by field, an
 * absent field is absent, and nothing is derived that the server did not send. The HTTP client is
 * replaced at the function boundary.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { DeskAction, DeskRun } from '../api/desk'

vi.mock('../api/client', async original => ({
  ...(await original<typeof import('../api/client')>()),
  getJson: vi.fn(),
  postJson: vi.fn(),
}))

import { ApiClientError, getJson, postJson } from '../api/client'
import { deskAction, deskRun, executedAction } from '../test/deskFixtures'
import { actionExtras, applyTaskUpdate, commandTextOf, dismissTaskUpdate, editsOf, fetchDeskMemory, runKindOf, taskUpdatesOf, wasEdited, type DeskMemory } from './deskContract'

const withFields = (action: DeskAction, extra: Record<string, unknown>): DeskAction => ({ ...action, ...extra }) as DeskAction
const runWith = (extra: Record<string, unknown>): DeskRun => ({ ...deskRun(), ...extra }) as DeskRun

beforeEach(() => {
  vi.resetAllMocks()
})

describe('the state of one action', () => {
  it('reads nothing from an action that carries none of the newer fields', () => {
    expect(actionExtras(deskAction())).toEqual({ lifecycle: null, retryMode: null, edited: [], effectiveInput: null, target: null })
  })

  it('reads the lifecycle, the retry mode, the edit and the target as the server sent them', () => {
    const extras = actionExtras(withFields(executedAction(), {
      lifecycle: 'VERIFIED',
      retry: { mode: 'readback_first' },
      edited: ['start', 'end'],
      effectiveInput: { title: 'Intro call', start: '2026-11-17T16:00:00+02:00' },
      target: { id: 'evt-1', title: 'Design workshop', start: '2026-11-17T10:00:00+02:00', end: '2026-11-17T11:00:00+02:00', provider: 'google' },
    }))
    expect(extras.lifecycle).toBe('VERIFIED')
    expect(extras.retryMode).toBe('readback_first')
    expect(extras.edited).toEqual(['start', 'end'])
    expect(extras.effectiveInput).toEqual({ title: 'Intro call', start: '2026-11-17T16:00:00+02:00' })
    expect(extras.target).toEqual({ id: 'evt-1', title: 'Design workshop', start: '2026-11-17T10:00:00+02:00', end: '2026-11-17T11:00:00+02:00', provider: 'google' })
  })

  it('keeps a lifecycle it does not know as sent, and drops values of the wrong shape', () => {
    const extras = actionExtras(withFields(deskAction(), {
      lifecycle: 'ARCHIVED_BY_POLICY',
      retry: { mode: 'whenever' },
      edited: ['start', 7, '', null],
      effectiveInput: ['start'],
      target: { id: 42, title: '  ' },
    }))
    expect(extras.lifecycle).toBe('ARCHIVED_BY_POLICY')
    expect(extras.retryMode).toBeNull()
    expect(extras.edited).toEqual(['start'])
    expect(extras.effectiveInput).toBeNull()
    expect(extras.target).toEqual({ id: null, title: null, start: null, end: null, provider: null })
    expect(actionExtras(withFields(deskAction(), { lifecycle: '', retry: 'rerun', edited: 'start', target: 'evt-1' }))).toEqual({ lifecycle: null, retryMode: null, edited: [], effectiveInput: null, target: null })
    for (const mode of ['rerun', 'readback_first', 'confirm_first']) expect(actionExtras(withFields(deskAction(), { retry: { mode } })).retryMode).toBe(mode)
  })
})

describe('what the person changed at approval', () => {
  const proposed = { title: 'Intro call', start: '2026-11-17T15:00:00+02:00', end: '2026-11-17T15:30:00+02:00' }
  const approved = { ...proposed, start: '2026-11-17T16:00:00+02:00', end: '2026-11-17T16:30:00+02:00' }

  it('lists each edited field with what was proposed and what was approved', () => {
    const action = withFields(executedAction({ input: proposed }), { edited: ['start', 'end'], effectiveInput: approved })
    expect(editsOf(action)).toEqual([
      { field: 'start', proposed: '2026-11-17T15:00:00+02:00', approved: '2026-11-17T16:00:00+02:00' },
      { field: 'end', proposed: '2026-11-17T15:30:00+02:00', approved: '2026-11-17T16:30:00+02:00' },
    ])
    // A field the person added has nothing on the proposed side, and that is shown, not filled in.
    expect(editsOf(withFields(executedAction({ input: proposed }), { edited: ['location'], effectiveInput: { ...proposed, location: 'Room 4' } }))).toEqual([{ field: 'location', proposed: undefined, approved: 'Room 4' }])
  })

  it('is empty when the backend does not send the effective input: the approved value is never guessed', () => {
    expect(editsOf(withFields(executedAction({ input: proposed }), { edited: ['start', 'end'] }))).toEqual([])
    expect(editsOf(withFields(executedAction({ input: proposed }), { edited: ['start'], effectiveInput: null }))).toEqual([])
  })

  it('is empty when nothing was edited, even with an effective input', () => {
    expect(editsOf(withFields(executedAction({ input: proposed }), { edited: [], effectiveInput: proposed }))).toEqual([])
    expect(editsOf(executedAction({ input: proposed }))).toEqual([])
  })

  it('knows a proposal was edited from the action or from its decisions, whether or not the values were sent', () => {
    expect(wasEdited(deskAction())).toBe(false)
    expect(wasEdited(withFields(deskAction(), { edited: ['body'] }))).toBe(true)
    expect(wasEdited(withFields(deskAction(), { edited: [] }))).toBe(false)
    expect(wasEdited(deskAction({ decisions: [{ decision: 'approve', by: 'exec@desk.example', at: '2026-11-14T08:05:00+00:00', edited: ['body'] }] }))).toBe(true)
    expect(wasEdited(deskAction({ decisions: [{ decision: 'approve', by: 'exec@desk.example', at: '2026-11-14T08:05:00+00:00', edited: [] }, { decision: 'approve', by: 'exec@desk.example', at: '2026-11-14T08:06:00+00:00' }] }))).toBe(false)
  })
})

describe('changes to an existing task', () => {
  it('reads each update the run reports', () => {
    expect(taskUpdatesOf(runWith({ taskUpdates: [
      { taskId: 't-9', title: 'Send the board pack', state: 'suggested', matched: ['title', 'sender'] },
      { taskId: 't-10', title: 'File expenses', state: 'completed', matched: [], verified: true },
      { taskId: 't-11', state: 'failed', error: 'The task store did not answer.', verified: false },
    ] }))).toEqual([
      { taskId: 't-9', title: 'Send the board pack', state: 'suggested', matched: ['title', 'sender'], verified: null, error: null },
      { taskId: 't-10', title: 'File expenses', state: 'completed', matched: [], verified: true, error: null },
      { taskId: 't-11', title: null, state: 'failed', matched: [], verified: false, error: 'The task store did not answer.' },
    ])
  })

  it('is empty on a run that reports none, and leaves out entries that name no task', () => {
    expect(taskUpdatesOf(deskRun())).toEqual([])
    expect(taskUpdatesOf(runWith({ taskUpdates: null }))).toEqual([])
    expect(taskUpdatesOf(runWith({ taskUpdates: { taskId: 't-9' } }))).toEqual([])
    expect(taskUpdatesOf(runWith({ taskUpdates: ['t-9', null, { title: 'No id' }, { taskId: '' }, { taskId: 't-12' }] }))).toEqual([
      { taskId: 't-12', title: null, state: 'unknown', matched: [], verified: null, error: null },
    ])
  })

  it('keeps a state it does not know as sent, and "verified" only as a boolean', () => {
    const [update] = taskUpdatesOf(runWith({ taskUpdates: [{ taskId: 't-9', state: 'snoozed', verified: 'yes' }] }))
    expect(update).toMatchObject({ state: 'snoozed', verified: null })
  })

  it('applies and dismisses an update on the run it belongs to', async () => {
    vi.mocked(postJson).mockResolvedValue(deskRun())
    await applyTaskUpdate(7, 'task 9/a')
    expect(postJson).toHaveBeenLastCalledWith('/desk/runs/7/task-updates/task%209%2Fa/apply')
    await dismissTaskUpdate(7, 't-9')
    expect(postJson).toHaveBeenLastCalledWith('/desk/runs/7/task-updates/t-9/dismiss')
  })
})

describe('what the Desk knows, read from records', () => {
  const memory: DeskMemory = {
    account: 'exec@desk.example',
    asOf: '2026-11-14T08:00:00+00:00',
    meetings: { ok: true, items: [] },
    tasks: { ok: true, items: [{ id: 't-9', title: 'Send the board pack', dueAt: null, overdue: false }] },
    waiting: { ok: false, items: [], error: 'timeout' },
  }

  it('returns the memory the backend sends', async () => {
    vi.mocked(getJson).mockResolvedValue(memory)
    await expect(fetchDeskMemory()).resolves.toBe(memory)
    expect(vi.mocked(getJson).mock.calls[0][0]).toBe('/desk/memory')
  })

  it('returns null on a backend that does not have the route', async () => {
    vi.mocked(getJson).mockRejectedValue(new ApiClientError('Not Found', { status: 404 }))
    await expect(fetchDeskMemory()).resolves.toBeNull()
    vi.mocked(getJson).mockRejectedValue(new ApiClientError('Method Not Allowed', { status: 405 }))
    await expect(fetchDeskMemory()).resolves.toBeNull()
  })

  it('lets every other failure through: a memory that could not be read is not "no memory"', async () => {
    vi.mocked(getJson).mockRejectedValue(new ApiClientError('Gateway timeout', { status: 504 }))
    await expect(fetchDeskMemory()).rejects.toThrow('Gateway timeout')
    vi.mocked(getJson).mockRejectedValue(new ApiClientError('Network Error'))
    await expect(fetchDeskMemory()).rejects.toThrow('Network Error')
    // Only the client's own error carries a status that means "no such route".
    vi.mocked(getJson).mockRejectedValue(Object.assign(new Error('Not Found'), { status: 404 }))
    await expect(fetchDeskMemory()).rejects.toThrow('Not Found')
  })
})

describe('the kind of a run', () => {
  it('is a message unless the server says it is an instruction, and reads the instruction text', () => {
    expect(runKindOf(deskRun())).toBe('email')
    expect(runKindOf(runWith({ kind: 'memo' }))).toBe('email')
    expect(runKindOf(runWith({ kind: 'command' }))).toBe('command')
    expect(commandTextOf(runWith({ kind: 'command', command: { text: 'Move my 3pm to Thursday' } }))).toBe('Move my 3pm to Thursday')
    expect(commandTextOf(runWith({ kind: 'command', command: { text: '  ' } }))).toBeNull()
    expect(commandTextOf(deskRun())).toBeNull()
  })
})
