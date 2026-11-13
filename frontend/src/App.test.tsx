import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ProviderDescriptor, ProviderStatusPayload } from './api/contract'

vi.mock('./api/scriba', async original => ({
  ...(await original<typeof import('./api/scriba')>()),
  fetchProviderStatus: vi.fn(),
  fetchHealth: vi.fn(),
  fetchEmails: vi.fn(),
  fetchCalendarEvents: vi.fn(),
  logout: vi.fn(),
}))

import App from './App'
import { fetchProviderStatus } from './api/scriba'

const row = (overrides: Partial<ProviderDescriptor> = {}): ProviderDescriptor => ({
  active: false, connected: false, available: true, configured: true,
  status: 'disconnected', reason: null, ...overrides,
})

const status = (overrides: Partial<ProviderStatusPayload>): ProviderStatusPayload => ({
  authorized: false, email: null, accountEmail: null, calendarAuthorized: false,
  gmailConnected: false, gmailEmail: null, outlookConnected: false, outlookEmail: null,
  outlookDisplayName: null,
  providers: {
    gmail: row({ loginPath: '/auth/login' }),
    google_calendar: row({ loginPath: '/auth/login' }),
    outlook: row({ loginPath: '/auth/outlook/login' }),
    outlook_calendar: row({ loginPath: '/auth/outlook/login' }),
    slack: row({ connected: true, status: 'connected' }),
  },
  ...overrides,
})

function renderApp() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <App />
    </QueryClientProvider>,
  )
}

describe('App', () => {
  beforeEach(() => {
    window.localStorage.clear()
    vi.mocked(fetchProviderStatus).mockReset()
  })

  it('shows sign-in with Google and Microsoft pointing at the Scriba API when anonymous', async () => {
    vi.mocked(fetchProviderStatus).mockResolvedValue(status({}))
    renderApp()

    const google = await screen.findByRole('link', { name: /continue with google/i })
    const microsoft = screen.getByRole('link', { name: /continue with microsoft/i })
    // The test origin is http://localhost:5173, so apiBase resolves to :8000.
    expect(google.getAttribute('href')).toBe('http://localhost:8000/auth/login')
    expect(microsoft.getAttribute('href')).toBe('http://localhost:8000/auth/outlook/login')
  })

  it('shows the four connection cards and no excluded integration when signed in', async () => {
    vi.mocked(fetchProviderStatus).mockResolvedValue(
      status({
        authorized: true,
        email: 'exec@example.test',
        providers: {
          gmail: row({ connected: true, status: 'connected', email: 'exec@gmail.example' }),
          google_calendar: row({ connected: true, status: 'connected', email: 'exec@gmail.example' }),
          outlook: row({ loginPath: '/auth/outlook/login' }),
          outlook_calendar: row({ loginPath: '/auth/outlook/login' }),
          slack: row({ connected: true, status: 'connected' }),
        },
      }),
    )
    renderApp()

    await waitFor(() => expect(screen.getByTestId('signed-in-as').textContent).toBe('exec@example.test'))
    expect(screen.getByTestId('readiness').textContent).toMatch(/ready/i)
    expect(screen.getByTestId('capability-gmail').textContent).toMatch(/Connected/)
    expect(screen.getByTestId('capability-google_calendar').textContent).toMatch(/Connected/)
    expect(screen.getByTestId('capability-outlook_mail').textContent).toMatch(/Not connected/)
    expect(screen.getByTestId('capability-outlook_calendar').textContent).toMatch(/Not connected/)
    expect(screen.getAllByRole('link', { name: /connect microsoft/i })[0].getAttribute('href'))
      .toBe('http://localhost:8000/auth/outlook/login')
    expect(document.body.textContent).not.toMatch(/slack|teams|jira|drive/i)
  })
})
