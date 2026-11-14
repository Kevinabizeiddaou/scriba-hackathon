/**
 * The Automations workspace: the workflow graph and what a run read, fetched and made. Every
 * assertion is about a state the backend reports; nothing here is drawn from a guess.
 */
import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DeskFileChange, DeskLifecycleStage, DeskRun, DeskTimelineItem } from '../api/desk'
import * as desk from '../api/desk'
import { deskAction, deskRun, executedAction } from '../test/deskFixtures'
import { RunDeliverables, describeOperation, type BrowserErrand } from './RunDeliverables'
import { WorkflowGraph, stageNotes } from './WorkflowGraph'
import { progressOf } from './runLifecycle'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

const lifecycle = (stage: string, reason: string | null = null): DeskRun['lifecycle'] => ({ stage: stage as DeskLifecycleStage, reason, final: false, compensation: null }) as DeskRun['lifecycle']
const at = (minute: number) => `2026-11-14T08:${String(minute).padStart(2, '0')}:00+00:00`
const event = (minute: number, kind: DeskTimelineItem['kind'], data: Record<string, unknown> = {}): DeskTimelineItem => ({ at: at(minute), kind, summary: '', data })
const opening = [event(0, 'stage', { stage: 'RECEIVED' }), event(1, 'stage', { stage: 'UNDERSTANDING' }), event(2, 'stage', { stage: 'INVESTIGATING' }), event(3, 'stage', { stage: 'PLANNING' })]

const graph = (run: DeskRun) => render(<WorkflowGraph steps={progressOf(run)!} timeZone="UTC" notes={stageNotes(run)} />)
const stateOf = (name: RegExp) => screen.getByRole('listitem', { name }).getAttribute('data-state')

describe('the workflow graph', () => {
  it('draws the stages the server recorded as done, the one the run rests in as now, and the rest as not yet', () => {
    graph(deskRun({ lifecycle: lifecycle('AWAITING_APPROVAL'), timeline: [...opening, event(4, 'proposal')], actions: [deskAction()] }))
    const list = screen.getByRole('list', { name: 'Progress of this run' })
    expect(within(list).getAllByRole('listitem')).toHaveLength(8)
    expect(stateOf(/^Incoming: done$/)).toBe('reached')
    expect(stateOf(/^Planning: done$/)).toBe('reached')
    const now = screen.getByRole('listitem', { name: 'Awaiting approval: now' })
    expect(now).toHaveAttribute('aria-current', 'step')
    expect(within(now).getByText(/1 action waiting for you/)).toBeInTheDocument()
    expect(stateOf(/^Executing: not yet$/)).toBe('upcoming')
    expect(stateOf(/^Completed: not yet$/)).toBe('upcoming')
  })

  it('never marks a stage done that the server did not record', () => {
    graph(deskRun({ lifecycle: lifecycle('EXECUTING'), timeline: [event(0, 'stage', { stage: 'RECEIVED' }), event(5, 'execution')], actions: [deskAction({ status: 'executing' })] }))
    expect(stateOf(/^Understanding: not recorded$/)).toBe('skipped')
    expect(stateOf(/^Awaiting approval: not recorded$/)).toBe('skipped')
    expect(stateOf(/^Executing: now$/)).toBe('current')
  })

  it('moves only while the secretary holds the next move', () => {
    const { container, unmount } = graph(deskRun({ lifecycle: lifecycle('EXECUTING'), timeline: [...opening, event(5, 'execution')], actions: [deskAction({ status: 'executing' })] }))
    expect(container.querySelector('.flow-link-live')).not.toBeNull()
    expect(container.querySelector('.flow-spin')).not.toBeNull()
    unmount()
    const waiting = graph(deskRun({ lifecycle: lifecycle('AWAITING_APPROVAL'), timeline: [...opening, event(4, 'proposal')], actions: [deskAction()] }))
    expect(waiting.container.querySelector('.flow-link-live')).toBeNull()
    expect(waiting.container.querySelector('.flow-spin')).toBeNull()
  })

  it('shows a failed run as failed, where it stopped, and nothing after it', () => {
    const { container } = graph(deskRun({ lifecycle: lifecycle('FAILED'), state: 'failed', timeline: [...opening, event(4, 'proposal'), event(5, 'execution')], actions: [deskAction({ status: 'failed' })], updatedAt: at(6) }))
    const items = screen.getAllByRole('listitem')
    expect(items[items.length - 1]).toHaveAccessibleName('Failed: now')
    expect(container.querySelector('.flow-node-danger')).not.toBeNull()
    expect(screen.queryByRole('listitem', { name: /Completed/ })).toBeNull()
    expect(screen.getByText('1 action failed')).toBeInTheDocument()
  })

  it('says how much was verified from the flags on the actions, not from their status', () => {
    const run = deskRun({ lifecycle: lifecycle('VERIFYING'), timeline: [...opening, event(4, 'proposal'), event(5, 'execution'), event(6, 'verification')], actions: [executedAction(), { ...executedAction(), toolCallId: 99, verified: false }] })
    expect(stageNotes(run).VERIFYING[0]).toMatchObject({ text: '1 of 2 verified', tone: 'warn' })
  })

  it('names an unknown stage as unrecognised and never as finished', () => {
    graph(deskRun({ lifecycle: lifecycle('ARCHIVED_BY_POLICY'), timeline: opening, updatedAt: at(9) }))
    const last = screen.getAllByRole('listitem').pop()!
    expect(last.getAttribute('aria-label')).toMatch(/ARCHIVED_BY_POLICY: now/)
    expect(last.querySelector('.flow-node-ok')).toBeNull()
  })
})

const change = (over: Partial<DeskFileChange> = {}): DeskFileChange => ({
  id: 'fc-1-1', state: 'suggested', sourceFileId: 'att-1', filename: 'budget.xlsx',
  operations: [{ op: 'update_cell', sheet: 'Budget', cell: 'C3', value: 520 }, { op: 'upsert_row', sheet: 'Budget', key: 'Department', values: { Department: 'HR', Actual: 310 } }],
  resultFileId: null, resultFilename: null, verified: false, verification: null, steps: [], failedAt: null, error: null, message: null,
  dismissedFrom: null, by: 'alice@example.com', updatedAt: at(5), simulated: true, apply: { method: 'POST', path: '/desk/runs/1/file-changes/fc-1-1/apply' }, ...over,
})

const shown = (run: DeskRun, onChanged = vi.fn()) =>
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { mutations: { retry: false } } })}><RunDeliverables run={run} onChanged={onChanged} /></QueryClientProvider>)

describe('what a run read, fetched and made', () => {
  it('shows nothing when the run has no files, changes or website errand', () => {
    const { container } = shown(deskRun({}))
    expect(container).toBeEmptyDOMElement()
  })

  it('applies a workbook change only when the user presses Apply, and says a copy is made', async () => {
    const applied = deskRun({ fileChanges: [change({ state: 'applied', verified: true, resultFilename: 'budget (updated).xlsx', apply: null })] })
    const apply = vi.spyOn(desk, 'applyDeskFileChange').mockResolvedValue(applied)
    const onChanged = vi.fn()
    shown(deskRun({ runId: 7, fileChanges: [change()] }), onChanged)
    const card = screen.getByTestId('file-change')
    expect(card).toHaveAttribute('data-state', 'suggested')
    expect(within(card).getByText(/A changed copy will be made and checked\. The original file stays as it is\./)).toBeInTheDocument()
    expect(within(card).getByText('Budget, cell C3: set to 520')).toBeInTheDocument()
    expect(within(card).getByText('Budget: where Department is HR, set Department = HR, Actual = 310')).toBeInTheDocument()
    expect(apply).not.toHaveBeenCalled()
    await userEvent.click(within(card).getByRole('button', { name: 'Apply to a copy' }))
    expect(apply).toHaveBeenCalledWith(7, 'fc-1-1')
    expect(onChanged.mock.calls[0][0]).toBe(applied)
  })

  it('never shows a failed, unconfirmed or set-aside change as applied', () => {
    shown(deskRun({ fileChanges: [
      change({ id: 'a', state: 'failed', failedAt: 2, message: 'Operation 2 did not take effect. Nothing was kept; the original is unchanged.', apply: null }),
      change({ id: 'b', state: 'unverified', apply: null }),
      change({ id: 'c', state: 'dismissed', dismissedFrom: 'failed', apply: null }),
    ] }))
    const cards = screen.getAllByTestId('file-change')
    expect(cards.map(card => card.getAttribute('data-state'))).toEqual(['failed', 'unverified', 'dismissed'])
    expect(screen.queryByText('Applied and verified')).toBeNull()
    expect(screen.queryByRole('button', { name: 'Apply to a copy' })).toBeNull()
    expect(within(cards[0]).getByText(/Nothing was kept; the original is unchanged/)).toBeInTheDocument()
    expect(within(cards[1]).getByText(/this is not a success/)).toBeInTheDocument()
    expect(within(cards[2]).getByText('Set aside after it was not applied.')).toBeInTheDocument()
  })

  it('marks a file verified only when the server says so, and says what was not read', () => {
    shown(deskRun({
      files: [
        { id: 'f1', filename: 'review.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', sizeBytes: 37000, toolCallId: 1, stepId: 's1', state: 'VERIFIED', verified: true, simulated: true, download: { method: 'GET', path: '/desk/files/f1' } },
        { id: 'f2', filename: 'broken.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', sizeBytes: 10, toolCallId: 2, stepId: 's2', state: 'VERIFICATION_FAILED', verified: false, simulated: true, download: { method: 'GET', path: '/desk/files/f2' } },
      ],
      attachments: [{ id: 'a1', filename: 'setup.exe', kind: null, sizeBytes: 900, sha256: null, read: false, error: 'file_blocked', unit: null, unitCount: null, truncated: false, unreadParts: 0, untrustedFindings: 0, unusual: 0, readAt: at(1) }],
    }))
    const files = screen.getByRole('region', { name: 'Files' })
    expect(within(files).getAllByText('Verified')).toHaveLength(1)
    expect(within(files).getByText('The file was written but does not show what was approved.')).toBeInTheDocument()
    expect(within(files).getByText(/Not read\. This kind of file is not opened\./)).toBeInTheDocument()
    expect(within(files).getByRole('button', { name: 'Download review.docx' })).toBeInTheDocument()
  })

  it('shows a website errand as the backend reports it: site, steps, evidence, and what was refused', () => {
    const browser: BrowserErrand = {
      state: 'VERIFIED', site: 'Northwind supplier portal', origin: 'http://127.0.0.1:5000', goal: 'Retrieve the latest report', stepsDone: 2, stepsTotal: 2, verified: true, simulated: true,
      steps: [
        { index: 1, op: 'follow', name: 'Reports', state: 'done', ms: 12.4, recovered: ['closed_dialog:Announcement'] },
        { index: 2, op: 'download', name: 'Download', state: 'done', ms: 40, verification: { verified: true, method: 'file_opened', checksum: 'matches_the_page' } },
      ],
      untrustedFindings: [{ url: 'http://127.0.0.1:5000/home', where: 'hidden', finding: 'x' }],
      ignored: [{ name: 'Download report (fast mirror)', reason: 'leads_to_another_site', origin: 'http://127.0.0.1:6000' }],
      blockedOrigins: [],
    }
    shown({ ...deskRun({}), browser } as DeskRun)
    const errand = screen.getByTestId('browser-errand')
    expect(errand).toHaveAttribute('data-state', 'VERIFIED')
    expect(within(errand).getByText('Done and verified')).toBeInTheDocument()
    expect(within(errand).getByText(/2 of 2 steps done on http:\/\/127\.0\.0\.1:5000/)).toBeInTheDocument()
    expect(within(errand).getByText('On the way: closed a dialog.')).toBeInTheDocument()
    expect(within(errand).getByText('The file was opened and has the checksum the page states.')).toBeInTheDocument()
    expect(within(errand).getByRole('alert')).toHaveTextContent('text written to an assistant (hidden in the page). It was not followed.')
    expect(within(errand).getByText(/A link to another site was not used: "Download report \(fast mirror\)"/)).toBeInTheDocument()
  })

  it('gives every errand state that is not success its own wording and never the word verified', () => {
    for (const state of ['FAILED', 'HELD', 'NEEDS_APPROVAL', 'NOT_APPLIED', 'OUTCOME_UNKNOWN', 'INTERRUPTED', 'SOMETHING_NEW']) {
      const { unmount } = shown({ ...deskRun({}), browser: { state, site: 'Portal', stepsDone: 1, stepsTotal: 5, verified: false, simulated: true, message: 'It stopped.' } } as DeskRun)
      const errand = screen.getByTestId('browser-errand')
      expect(errand).not.toHaveTextContent(/verified/i)
      expect(within(errand).getByRole('alert')).toHaveTextContent('It stopped.')
      unmount()
    }
  })

  it('writes a change in words a person can check', () => {
    expect(describeOperation({ op: 'append_row', sheet: 'Budget', values: { Department: 'HR', Planned: 300 } })).toBe('Budget: add a row (Department = HR, Planned = 300)')
    expect(describeOperation({ op: 'update_cell', sheet: 'Budget', cell: 'A2', value: null })).toBe('Budget, cell A2: set to empty')
  })
})
