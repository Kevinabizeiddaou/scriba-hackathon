/**
 * The Scriba endpoints the Executive Desk calls in Stage 1. All of them exist
 * on Scriba at 3ae3a2aa and are owned there; nothing here is a new backend.
 *
 * Paths mirror Gmail/frontend/src/api/index.ts (fetchProviderStatus 363,
 * logout 364, fetchEmails 531, fetchCalendarEvents 764).
 */
import { backendUrl, getJson, postJson } from './client'
import type {
  CalendarEventsPayload,
  CalendarProvider,
  EmailListResponse,
  HealthPayload,
  MailProvider,
  ProviderStatusPayload,
} from './contract'

export const fetchProviderStatus = () =>
  getJson<ProviderStatusPayload>('/providers/status')

export const fetchHealth = () => getJson<HealthPayload>('/health')

export const logout = () => postJson<{ status: string }>('/auth/logout')

// A live Gmail page costs one list call plus one get per row for every
// connected account, so a stalled backend must fail rather than spin forever
// (same bound as Scriba's EMAIL_LIST_TIMEOUT_MS).
const EMAIL_LIST_TIMEOUT_MS = 90_000

export const fetchEmails = (
  provider: MailProvider,
  options?: { limit?: number; cursor?: string; mailbox?: string },
) =>
  getJson<EmailListResponse>('/emails', {
    params: {
      provider,
      limit: options?.limit ?? 25,
      cursor: options?.cursor,
      mailbox: options?.mailbox || undefined,
    },
    timeout: EMAIL_LIST_TIMEOUT_MS,
  })

export const fetchCalendarEvents = (
  provider: CalendarProvider,
  range?: { start?: string; end?: string },
) =>
  getJson<CalendarEventsPayload>('/calendar/events', {
    params: { provider, start: range?.start, end: range?.end },
  })

/**
 * OAuth starts with a full-page navigation to the EXISTING Scriba API host,
 * which owns the registered Google and Microsoft callbacks. The Desk never
 * handles a code, a token or a client secret.
 */
export const GOOGLE_LOGIN_PATH = '/auth/login'
export const MICROSOFT_LOGIN_PATH = '/auth/outlook/login'

export const googleLoginUrl = (options?: { addAccount?: boolean; loginHint?: string }) => {
  const url = new URL(backendUrl(GOOGLE_LOGIN_PATH), window.location.origin)
  if (options?.addAccount) url.searchParams.set('intent', 'add_account')
  if (options?.loginHint) url.searchParams.set('login_hint', options.loginHint)
  return url.toString()
}

export const microsoftLoginUrl = () => backendUrl(MICROSOFT_LOGIN_PATH)
