/**
 * Fields the backend sends that the typed client on `main` (src/api/desk.ts) does not declare yet.
 *
 * The typed client belongs to the backend owner and is being reconciled on their branches
 * (overlay 0.3.1 on agent1/engine-reconciliation, overlay 0.4 on agent1/autonomous-engine). Until
 * one client is merged, the screens read the newer fields here: as untyped data, checked field by
 * field, so this compiles against either client and a field that is absent is simply absent.
 * Nothing is derived that the server did not send. When the reconciled client lands, each reader
 * below becomes a plain property access (docs/AGENT2_FRONTEND_HANDOFF.md lists them).
 */
import { ApiClientError, getJson, postJson } from '../api/client'
import type { DeskAction, DeskFollowUp, DeskRun } from '../api/desk'

const record = (value: unknown): Record<string, unknown> | null => (value !== null && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : null)
const text = (value: unknown): string | null => (typeof value === 'string' && value.trim() ? value : null)
const texts = (value: unknown): string[] => (Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string' && item.trim() !== '') : [])

// ── the state of one action (overlay 0.3.1) ─────────────────────────────────

/** `DeskAction.lifecycle` as the backend sends it. Only `VERIFIED` is done. */
export const ACTION_LIFECYCLES = ['PROPOSED', 'HELD', 'APPROVED', 'EXECUTING', 'EXECUTED_UNVERIFIED', 'VERIFIED', 'VERIFICATION_FAILED', 'PARTIALLY_EXECUTED', 'OUTCOME_UNKNOWN', 'INTERRUPTED', 'FAILED', 'REJECTED'] as const
export type ActionLifecycle = (typeof ACTION_LIFECYCLES)[number]

export interface ActionExtras {
  /** The server's explicit state of the action. Null on a backend that does not send it; a value this client does not know is kept as sent. */
  lifecycle: ActionLifecycle | string | null
  retryMode: 'rerun' | 'readback_first' | 'confirm_first' | null
  /** The fields the person changed in the approve request. `input` stays as proposed. */
  edited: string[]
  /** The action as it ran, or will run: `input` with the person's edit applied. Null when not sent. */
  effectiveInput: Record<string, unknown> | null
  /** The existing meeting a calendar change is about (overlay 0.4). */
  target: { id: string | null; title: string | null; start: string | null; end: string | null; provider: string | null } | null
}

export function actionExtras(action: DeskAction): ActionExtras {
  const raw = action as unknown as Record<string, unknown>
  const retry = record(raw.retry)
  const mode = text(retry?.mode)
  const target = record(raw.target)
  return {
    lifecycle: text(raw.lifecycle),
    retryMode: mode === 'rerun' || mode === 'readback_first' || mode === 'confirm_first' ? mode : null,
    edited: texts(raw.edited),
    effectiveInput: record(raw.effectiveInput),
    target: target ? { id: text(target.id), title: text(target.title), start: text(target.start), end: text(target.end), provider: text(target.provider) } : null,
  }
}

/** One field the person changed at approval: what was proposed, and what was approved and ran. */
export interface EditedField {
  field: string
  proposed: unknown
  approved: unknown
}

/**
 * The person's edits, field by field. Empty when nothing was edited, or when the backend does not
 * send the effective input: then the screen cannot show the approved value and must not guess it.
 */
export function editsOf(action: DeskAction): EditedField[] {
  const { edited, effectiveInput } = actionExtras(action)
  if (edited.length === 0 || !effectiveInput) return []
  return edited.map(field => ({ field, proposed: action.input?.[field], approved: effectiveInput[field] }))
}

/** True when the approve request changed the proposal, whether or not the approved values were sent. */
export function wasEdited(action: DeskAction): boolean {
  return actionExtras(action).edited.length > 0 || (action.decisions ?? []).some(decision => (decision.edited?.length ?? 0) > 0)
}

// ── changes to an existing task (overlay 0.3.1) ─────────────────────────────

export interface TaskUpdateView {
  taskId: string
  title: string | null
  state: 'suggested' | 'completed' | 'unverified' | 'failed' | 'dismissed' | string
  matched: string[]
  verified: boolean | null
  error: string | null
}

export function taskUpdatesOf(run: DeskRun): TaskUpdateView[] {
  const raw = (run as unknown as Record<string, unknown>).taskUpdates
  if (!Array.isArray(raw)) return []
  return raw
    .map(record)
    .filter((item): item is Record<string, unknown> => item !== null && (text(item.taskId) !== null || typeof item.taskId === 'number'))
    .map(item => ({
      taskId: String(item.taskId),
      title: text(item.title),
      state: text(item.state) ?? 'unknown',
      matched: texts(item.matched),
      verified: typeof item.verified === 'boolean' ? item.verified : null,
      error: text(item.error),
    }))
}

export const applyTaskUpdate = (runId: number, taskId: string) => postJson<DeskRun>(`/desk/runs/${runId}/task-updates/${encodeURIComponent(taskId)}/apply`)
export const dismissTaskUpdate = (runId: number, taskId: string) => postJson<DeskRun>(`/desk/runs/${runId}/task-updates/${encodeURIComponent(taskId)}/dismiss`)

// ── what the Desk knows, read from records (overlay 0.4: GET /desk/memory) ──

/** One part of the memory. `ok: false` means it could not be read: unknown, never "none". */
export interface MemoryPart<T> {
  ok: boolean
  items: T[]
  error?: string
}

export interface MemoryMeeting {
  id: string
  title: string
  start: string
  end: string
  attendees: string[]
  organizer: boolean
  provider: string
}

export interface MemoryTask {
  id: string
  title: string | null
  dueAt: string | null
  overdue: boolean
}

export interface DeskMemory {
  account: string
  asOf: string
  meetings: MemoryPart<MemoryMeeting>
  tasks: MemoryPart<MemoryTask>
  waiting: MemoryPart<Partial<DeskFollowUp>>
}

/**
 * GET /desk/memory, or null on a backend that does not have the route (before overlay 0.4). In a
 * sandbox this is the world's own calendar and tasks; Scriba's `/calendar/events` and `/tasks`
 * are not, and are never shown as if they were.
 */
export async function fetchDeskMemory(): Promise<DeskMemory | null> {
  try {
    return await getJson<DeskMemory>('/desk/memory', { timeout: 90_000 })
  } catch (error) {
    if (error instanceof ApiClientError && (error.status === 404 || error.status === 405)) return null
    throw error
  }
}

// ── requests the Desk read and could not act on (overlay 0.5) ───────────────

export interface UnresolvedRequest {
  id: string
  text: string
  why: string | null
  resolved: boolean
}

/** `DeskRun.unresolved`: while one is not resolved, the run is not complete. Empty on older backends. */
export function unresolvedOf(run: DeskRun): UnresolvedRequest[] {
  const raw = (run as unknown as Record<string, unknown>).unresolved
  if (!Array.isArray(raw)) return []
  return raw
    .map(record)
    .filter((item): item is Record<string, unknown> => item !== null && text(item.text) !== null)
    .map((item, index) => ({ id: text(item.id) ?? String(index), text: text(item.text)!, why: text(item.why), resolved: item.resolved === true }))
}

/** The person takes the unresolved requests over. Records that; sends nothing. */
export const resolveUnresolved = (runId: number) => postJson<DeskRun>(`/desk/runs/${runId}/unresolved/resolve`)

/** The run's kind (overlay 0.4): a message, or an instruction typed to the Desk. */
export function runKindOf(run: DeskRun): 'email' | 'command' {
  return (run as unknown as Record<string, unknown>).kind === 'command' ? 'command' : 'email'
}

/** The text of the instruction, for a command run. */
export function commandTextOf(run: DeskRun): string | null {
  return text(record((run as unknown as Record<string, unknown>).command)?.text)
}
