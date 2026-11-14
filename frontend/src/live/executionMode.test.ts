/**
 * What an approval does on this backend, as read from GET /desk/health. "Connected" and "carries
 * out real writes" are separate facts, a sandbox wins over every switch, and anything the server
 * does not report is treated as off.
 */
import { describe, expect, it } from 'vitest'
import type { DeskHealth } from '../api/desk'
import { deskModeFrom, executedLabel, isSimulated, type ExecutionKind } from './executionMode'

const health = (extra: Partial<DeskHealth> = {}): DeskHealth => ({ ok: true, service: 'scriba-desk-overlay', version: '0.4.0', scribaCommit: null, capabilities: [], writes: false, ...extra })

describe('the execution mode of a backend', () => {
  it('is a sandbox whenever the server says so, even with external writes enabled', () => {
    const mode = deskModeFrom(health({ executionMode: 'sandbox', sandbox: { id: 'w-1', label: 'Demo office' }, externalWrites: { enabled: true, authorized: true } }), 'ok')
    expect(mode).toMatchObject({ kind: 'sandbox', badge: 'SANDBOX', tone: 'sandbox', simulated: true, externalWrites: false, connected: true, authorized: true, world: 'Demo office' })
    expect(mode.title).toBe('Sandbox: simulated execution')
    expect(mode.detail).toContain('No real email is sent')
    // The world is named by its label, then by its id, and not at all when the server names none.
    expect(deskModeFrom(health({ executionMode: 'sandbox', sandbox: { id: 'w-1', label: '' } }), 'ok').world).toBe('w-1')
    expect(deskModeFrom(health({ executionMode: 'sandbox' }), 'ok')).toMatchObject({ kind: 'sandbox', world: null, authorized: null })
  })

  it('is live only when external writes are enabled and the server does not hold them', () => {
    const live = deskModeFrom(health({ executionMode: 'external', externalWrites: { enabled: true, authorized: true } }), 'ok')
    expect(live).toMatchObject({ kind: 'external', badge: 'LIVE', tone: 'live', externalWrites: true, simulated: false, connected: true })
    expect(live.detail).toContain('cannot be taken back')
    // An older overlay sends the switch without an execution mode.
    expect(deskModeFrom(health({ externalWrites: { enabled: true } }), 'ok').kind).toBe('external')
    // `external` without the switch is a contradiction: the switch is what the server enforces.
    expect(deskModeFrom(health({ executionMode: 'external', externalWrites: { enabled: false } }), 'ok').kind).toBe('disabled')
    expect(deskModeFrom(health({ executionMode: 'external' }), 'ok').kind).toBe('disabled')
    // Anything but a literal true is not enabled.
    expect(deskModeFrom(health({ externalWrites: { enabled: 'yes' as unknown as boolean } }), 'ok').kind).toBe('disabled')
  })

  it('is disabled when writes are held, switched off or not reported', () => {
    const held = deskModeFrom(health({ executionMode: 'held', externalWrites: { enabled: true, authorized: true, message: 'The mailbox token has not been checked.' } }), 'ok')
    expect(held).toMatchObject({ kind: 'disabled', badge: 'WRITES OFF', tone: 'off', externalWrites: false, simulated: false, connected: true, authorized: true })
    expect(held.title).toBe('Connected: external writes disabled')
    // Authorized by the project lead and still off: the note says a readiness check has not passed, and why.
    expect(held.detail).toContain('although the project lead has authorized them: a readiness check has not passed')
    expect(held.detail).toContain('The mailbox token has not been checked.')

    const absent = deskModeFrom(health(), 'ok')
    expect(absent).toMatchObject({ kind: 'disabled', badge: 'WRITES OFF', authorized: null, externalWrites: false })
    expect(absent.detail).not.toContain('authorized')
    expect(deskModeFrom(health({ externalWrites: { enabled: false, authorized: false } }), 'ok')).toMatchObject({ kind: 'disabled', authorized: false })
  })

  it('says what it does not know when the overlay is missing, failed or still being asked', () => {
    const missing = deskModeFrom(null, 'missing')
    expect(missing).toMatchObject({ kind: 'no_overlay', badge: 'WRITES OFF', tone: 'off', connected: true, externalWrites: false, simulated: false })
    expect(missing.title).toBe('Connected to Scriba, without the Desk overlay')
    // A health payload left over from before does not turn a missing overlay into a mode.
    expect(deskModeFrom(health({ executionMode: 'sandbox' }), 'missing').kind).toBe('no_overlay')

    const error = deskModeFrom(undefined, 'error')
    expect(error).toMatchObject({ kind: 'unknown', badge: 'MODE UNKNOWN', tone: 'unknown', connected: false, externalWrites: false })
    expect(deskModeFrom(health({ externalWrites: { enabled: true } }), 'error').kind).toBe('unknown')
    // The overlay answered but the payload is not there: unknown, never assumed real or safe.
    expect(deskModeFrom(null, 'ok')).toMatchObject({ kind: 'unknown', connected: false })

    const checking = deskModeFrom(undefined, 'checking')
    expect(checking).toMatchObject({ kind: 'checking', badge: 'CHECKING', tone: 'unknown', connected: false, externalWrites: false })
    expect(deskModeFrom(health({ externalWrites: { enabled: true } }), 'checking').kind).toBe('checking')
  })

  it('marks results as simulated in a sandbox and nowhere else, and real writes only when live', () => {
    const modes: Record<ExecutionKind, ReturnType<typeof deskModeFrom>> = {
      sandbox: deskModeFrom(health({ executionMode: 'sandbox' }), 'ok'),
      external: deskModeFrom(health({ externalWrites: { enabled: true } }), 'ok'),
      disabled: deskModeFrom(health(), 'ok'),
      no_overlay: deskModeFrom(null, 'missing'),
      unknown: deskModeFrom(null, 'error'),
      checking: deskModeFrom(null, 'checking'),
    }
    for (const [kind, mode] of Object.entries(modes)) {
      expect(mode.kind, kind).toBe(kind)
      expect(mode.simulated, kind).toBe(kind === 'sandbox')
      expect(mode.externalWrites, kind).toBe(kind === 'external')
      expect(mode.badge === 'LIVE', kind).toBe(kind === 'external')
      expect(mode.title.length, kind).toBeGreaterThan(10)
      expect(mode.detail.length, kind).toBeGreaterThan(10)
    }
  })
})

describe('the word for an action that ran', () => {
  it('never says a sandbox action was simply executed, and says verified only when it was', () => {
    expect(executedLabel(true)).toBe('Executed in sandbox')
    expect(executedLabel(true, true)).toBe('Executed in sandbox, verified')
    expect(executedLabel(true, false)).toBe('Executed in sandbox')
    expect(executedLabel(false)).toBe('Executed')
    expect(executedLabel(false, true)).toBe('Executed, verified')
    expect(executedLabel(false, null)).toBe('Executed')
  })

  it("takes an item's own flag before the session's mode", () => {
    expect(isSimulated({ simulated: false }, { simulated: true })).toBe(false)
    expect(isSimulated({ simulated: true }, { simulated: false })).toBe(true)
    expect(isSimulated({}, { simulated: true })).toBe(true)
    expect(isSimulated(null, { simulated: false })).toBe(false)
  })
})
