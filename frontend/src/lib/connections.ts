/**
 * The Desk's view of "what is connected": exactly four capabilities across two
 * identity providers. Built from Scriba's GET /providers/status, which also
 * reports Slack, Teams, Jira, Drive and OneDrive. Those are excluded from this
 * product, so they are dropped here and never reach a component.
 */
import type { ProviderDescriptor, ProviderStatusPayload } from '../api/contract'

export type CapabilityId = 'gmail' | 'google_calendar' | 'outlook_mail' | 'outlook_calendar'
export type Vendor = 'google' | 'microsoft'
export type ConnectionState = 'connected' | 'reconnect_required' | 'disconnected' | 'unavailable'

export interface Capability {
  id: CapabilityId
  vendor: Vendor
  label: string
  state: ConnectionState
  email: string | null
  /** Scriba's machine-readable reason, when it gives one. */
  reason: string | null
  /** Backend path that starts (or repairs) the connection. */
  loginPath: string
}

const SOURCES: ReadonlyArray<{
  id: CapabilityId
  key: 'gmail' | 'google_calendar' | 'outlook' | 'outlook_calendar'
  vendor: Vendor
  label: string
  loginPath: string
}> = [
  { id: 'gmail', key: 'gmail', vendor: 'google', label: 'Gmail', loginPath: '/auth/login' },
  { id: 'google_calendar', key: 'google_calendar', vendor: 'google', label: 'Google Calendar', loginPath: '/auth/login' },
  { id: 'outlook_mail', key: 'outlook', vendor: 'microsoft', label: 'Outlook Mail', loginPath: '/auth/outlook/login' },
  { id: 'outlook_calendar', key: 'outlook_calendar', vendor: 'microsoft', label: 'Outlook Calendar', loginPath: '/auth/outlook/login' },
]

export const EXCLUDED_PROVIDER_KEYS = [
  'slack', 'teams', 'jira', 'google_drive', 'onedrive',
] as const

function stateOf(descriptor: ProviderDescriptor | undefined): ConnectionState {
  if (!descriptor) return 'unavailable'
  // A provider the server is not configured for can never be connected from
  // the Desk, whatever else the row says.
  if (descriptor.available === false || descriptor.configured === false) return 'unavailable'
  if (descriptor.reconnectRequired || descriptor.status === 'reconnect_required') {
    return 'reconnect_required'
  }
  // `connected` is the server's verdict; `status` alone is not trusted.
  if (descriptor.connected === true) return 'connected'
  return 'disconnected'
}

export function capabilitiesFrom(status: ProviderStatusPayload | undefined | null): Capability[] {
  return SOURCES.map(source => {
    const descriptor = status?.providers?.[source.key]
    return {
      id: source.id,
      vendor: source.vendor,
      label: source.label,
      state: stateOf(descriptor),
      email: descriptor?.email ?? null,
      reason: descriptor?.reason ?? null,
      loginPath: descriptor?.loginPath || source.loginPath,
    }
  })
}

export function capability(
  status: ProviderStatusPayload | undefined | null,
  id: CapabilityId,
): Capability {
  return capabilitiesFrom(status).find(item => item.id === id)!
}

/** True when at least one mailbox AND one calendar are usable. */
export function secretaryReady(status: ProviderStatusPayload | undefined | null): boolean {
  const all = capabilitiesFrom(status)
  const connected = (ids: CapabilityId[]) =>
    all.some(item => ids.includes(item.id) && item.state === 'connected')
  return connected(['gmail', 'outlook_mail']) && connected(['google_calendar', 'outlook_calendar'])
}

export const STATE_LABEL: Record<ConnectionState, string> = {
  connected: 'Connected',
  reconnect_required: 'Reconnect needed',
  disconnected: 'Not connected',
  unavailable: 'Not available on this server',
}
