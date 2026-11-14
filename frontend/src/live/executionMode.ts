/**
 * What this backend does when an action is approved, in words a person cannot misread.
 *
 * Everything here comes from GET /desk/health (BACKEND_CONTRACT, "Health and readiness"). Being
 * connected to a real backend and carrying out real writes are two different facts, and the
 * sidebar used to merge them into one green "Live". They are kept apart:
 *
 *   - connection: is a Scriba backend answering, and does it have the Desk overlay;
 *   - execution: what an approved mail or calendar action does for THIS user. `sandbox` means it
 *     is applied to an isolated provider world and nothing real is reached; `external` means a
 *     real provider; `held` means the server refuses it.
 *
 * A sandbox wins over everything else: when the server reports `executionMode: "sandbox"` the
 * user has an isolated world in force, and every approval lands there whatever the readiness
 * switches say. Anything the server does not report is "not reported", never assumed real and
 * never assumed safe.
 */
import type { DeskHealth } from '../api/desk'

export type ExecutionKind =
  /** Approved actions run against an isolated provider world. Nothing real is sent or changed. */
  | 'sandbox'
  /** Approved actions reach a real mailbox or calendar. */
  | 'external'
  /** Mail and calendar writes are refused by the server. */
  | 'disabled'
  /** The backend is Scriba without the Desk overlay: it cannot say, so the Desk treats writes as off. */
  | 'no_overlay'
  /** The overlay could not be asked. Unknown is treated as off. */
  | 'unknown'
  | 'checking'

export type ModeTone = 'sandbox' | 'live' | 'off' | 'unknown'

export interface DeskMode {
  kind: ExecutionKind
  /** A real backend is answering (as opposed to the mock, or no answer). */
  connected: boolean
  /** True only in a sandbox: results are simulated and must be labelled as such everywhere. */
  simulated: boolean
  /** True only when an approval is carried out on a real provider. */
  externalWrites: boolean
  /** The project lead's switch, as reported. Not sufficient on its own. Null when not reported. */
  authorized: boolean | null
  tone: ModeTone
  /** The short, upper-case marker: SANDBOX, LIVE, WRITES OFF. */
  badge: string
  /** One line for the banner and the sidebar. */
  title: string
  /** What an approval does, in one or two sentences. */
  detail: string
  /** The sandbox world's name, when the server gives one. */
  world: string | null
}

type Overlay = 'checking' | 'ok' | 'missing' | 'error'

export function deskModeFrom(health: DeskHealth | null | undefined, overlay: Overlay): DeskMode {
  const base = { connected: overlay === 'ok' || overlay === 'missing', simulated: false, externalWrites: false, authorized: null as boolean | null, world: null as string | null }
  if (overlay === 'checking') {
    return { ...base, connected: false, kind: 'checking', tone: 'unknown', badge: 'CHECKING', title: 'Checking how this backend executes actions', detail: 'Until the backend answers, nothing can be approved that reaches a mailbox or a calendar.' }
  }
  if (overlay === 'missing') {
    return { ...base, kind: 'no_overlay', tone: 'off', badge: 'WRITES OFF', title: 'Connected to Scriba, without the Desk overlay', detail: 'This backend cannot report its safety checks, so sending mail and changing calendars stay switched off here. Tasks and reminders can be approved.' }
  }
  if (overlay === 'error' || !health) {
    return { ...base, connected: false, kind: 'unknown', tone: 'unknown', badge: 'MODE UNKNOWN', title: 'The execution mode could not be read', detail: 'The Desk could not ask the backend what an approval does. It treats external writes as off until it can.' }
  }
  const authorized = typeof health.externalWrites?.authorized === 'boolean' ? health.externalWrites.authorized : null
  const enabled = health.externalWrites?.enabled === true
  if (health.executionMode === 'sandbox') {
    const world = health.sandbox?.label || health.sandbox?.id || null
    return {
      ...base,
      authorized,
      kind: 'sandbox',
      simulated: true,
      tone: 'sandbox',
      badge: 'SANDBOX',
      world,
      title: 'Sandbox: simulated execution',
      detail: 'The mail, calendars and people here are synthetic. An approved action runs against an isolated stand-in and is read back there. No real email is sent, no real calendar is changed and no real person is contacted.',
    }
  }
  // `external` without the readiness switch would be a contradiction; the switch is what the server enforces.
  if (enabled && health.executionMode !== 'held') {
    return { ...base, authorized, kind: 'external', externalWrites: true, tone: 'live', badge: 'LIVE', title: 'Live: external writes authorized', detail: 'An approval you give is carried out on the real mailbox or calendar and cannot be taken back.' }
  }
  const why = health.externalWrites?.message?.trim()
  return {
    ...base,
    authorized,
    kind: 'disabled',
    tone: 'off',
    badge: 'WRITES OFF',
    title: 'Connected: external writes disabled',
    detail: `Sending mail and changing calendars are refused by this backend${authorized ? ', although the project lead has authorized them: a readiness check has not passed' : ''}. ${why ? `${why} ` : ''}You can review and cancel those actions; tasks and reminders can be approved.`,
  }
}

/**
 * The word for an action that ran. In a sandbox "sent" and "created" would read as if a real
 * person had been contacted, so the sandbox has its own words.
 */
export function executedLabel(simulated: boolean, verified: boolean | null = null): string {
  if (simulated) return verified === true ? 'Executed in sandbox, verified' : 'Executed in sandbox'
  return verified === true ? 'Executed, verified' : 'Executed'
}

/** Whether one item (a run, an action) is simulated: its own flag first, then the session's mode. */
export function isSimulated(item: { simulated?: boolean } | null | undefined, mode: Pick<DeskMode, 'simulated'>): boolean {
  if (item && typeof item.simulated === 'boolean') return item.simulated
  return mode.simulated
}
