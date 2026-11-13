import { describe, expect, it } from 'vitest'
import type { ProviderDescriptor, ProviderStatusPayload } from '../api/contract'
import { EXCLUDED_PROVIDER_KEYS, capabilitiesFrom, capability, secretaryReady } from './connections'

const descriptor = (overrides: Partial<ProviderDescriptor> = {}): ProviderDescriptor => ({
  active: false,
  connected: false,
  available: true,
  configured: true,
  status: 'disconnected',
  reason: null,
  ...overrides,
})

const connected = (email: string) =>
  descriptor({ active: true, connected: true, status: 'connected', email })

// Mirrors the shape Scriba returned at 3ae3a2aa, including the integrations
// the Desk excludes.
const payload = (providers: Partial<ProviderStatusPayload['providers']>): ProviderStatusPayload => ({
  authorized: true,
  email: 'exec@example.test',
  accountEmail: 'exec@example.test',
  calendarAuthorized: false,
  gmailConnected: false,
  gmailEmail: null,
  outlookConnected: false,
  outlookEmail: null,
  outlookDisplayName: null,
  providers: {
    gmail: descriptor(),
    google_calendar: descriptor(),
    outlook: descriptor(),
    outlook_calendar: descriptor(),
    slack: connected('slack-user'),
    teams: connected('teams-user'),
    jira: connected('jira-user'),
    google_drive: connected('drive-user'),
    onedrive: connected('onedrive-user'),
    ...providers,
  } as ProviderStatusPayload['providers'],
})

describe('capabilitiesFrom', () => {
  it('returns exactly the four Desk capabilities, Google then Microsoft', () => {
    const ids = capabilitiesFrom(payload({})).map(item => item.id)
    expect(ids).toEqual(['gmail', 'google_calendar', 'outlook_mail', 'outlook_calendar'])
  })

  it('never surfaces an excluded integration, even when Scriba says it is connected', () => {
    const text = JSON.stringify(capabilitiesFrom(payload({})))
    for (const key of EXCLUDED_PROVIDER_KEYS) expect(text).not.toContain(key)
    expect(text).not.toContain('slack-user')
  })

  it('maps Google and Microsoft independently', () => {
    const status = payload({
      gmail: connected('exec@gmail.example'),
      outlook_calendar: connected('exec@contoso.example'),
    })
    expect(capability(status, 'gmail')).toMatchObject({ state: 'connected', vendor: 'google', email: 'exec@gmail.example' })
    expect(capability(status, 'google_calendar').state).toBe('disconnected')
    expect(capability(status, 'outlook_mail').state).toBe('disconnected')
    expect(capability(status, 'outlook_calendar')).toMatchObject({ state: 'connected', vendor: 'microsoft' })
  })

  it('reports a server without Microsoft credentials as unavailable, not disconnected', () => {
    const status = payload({
      outlook: descriptor({ available: false, configured: false, status: 'unavailable', reason: 'missing_credentials' }),
    })
    expect(capability(status, 'outlook_mail')).toMatchObject({ state: 'unavailable', reason: 'missing_credentials' })
  })

  it('treats a revoked grant as reconnect_required even if the row still says connected', () => {
    const status = payload({
      gmail: descriptor({ connected: true, status: 'connected', reconnectRequired: true }),
    })
    expect(capability(status, 'gmail').state).toBe('reconnect_required')
  })

  it('does not trust a status string without the connected flag', () => {
    const status = payload({ gmail: descriptor({ connected: false, status: 'connected' }) })
    expect(capability(status, 'gmail').state).toBe('disconnected')
  })

  it('uses the login path the server gives, falling back to the known routes', () => {
    const status = payload({ outlook: descriptor({ loginPath: '/auth/outlook/login' }) })
    expect(capability(status, 'outlook_mail').loginPath).toBe('/auth/outlook/login')
    expect(capability(status, 'gmail').loginPath).toBe('/auth/login')
  })

  it('is safe on a missing payload', () => {
    expect(capabilitiesFrom(undefined).every(item => item.state === 'unavailable')).toBe(true)
  })
})

describe('secretaryReady', () => {
  it('needs one mailbox and one calendar, from either vendor', () => {
    expect(secretaryReady(payload({ gmail: connected('a') }))).toBe(false)
    expect(secretaryReady(payload({ google_calendar: connected('a') }))).toBe(false)
    expect(secretaryReady(payload({ gmail: connected('a'), outlook_calendar: connected('b') }))).toBe(true)
    expect(secretaryReady(payload({ outlook: connected('a'), outlook_calendar: connected('a') }))).toBe(true)
  })
})
