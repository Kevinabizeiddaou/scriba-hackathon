import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { setUnauthenticatedHandler } from './api/client'
import { logout } from './api/scriba'
import {
  PROVIDER_STATUS_QUERY_KEY,
  clearProviderStatusCache,
  useProviderStatus,
} from './hooks/useProviderStatus'
import { capabilitiesFrom, secretaryReady } from './lib/connections'
import { SignIn } from './shell/SignIn'
import { ConnectionsPanel } from './shell/ConnectionsPanel'
import { InboxPanel } from './shell/InboxPanel'
import { CalendarPanel } from './shell/CalendarPanel'
import { SystemPanel } from './shell/SystemPanel'

type TabId = 'connections' | 'inbox' | 'calendar' | 'system'

const TABS: ReadonlyArray<{ id: TabId; label: string; icon: string }> = [
  { id: 'connections', label: 'Connections', icon: 'fa-plug' },
  { id: 'inbox', label: 'Inbox', icon: 'fa-inbox' },
  { id: 'calendar', label: 'Calendar', icon: 'fa-calendar-days' },
  { id: 'system', label: 'System', icon: 'fa-heart-pulse' },
]

export default function App() {
  const queryClient = useQueryClient()
  const status = useProviderStatus()
  const [tab, setTab] = useState<TabId>('connections')

  // A 401 from any endpoint means the session is gone: drop the cached
  // snapshot and re-read provider status, which lands on the sign-in screen.
  useEffect(() => {
    setUnauthenticatedHandler(() => {
      clearProviderStatusCache()
      void queryClient.invalidateQueries({ queryKey: PROVIDER_STATUS_QUERY_KEY })
    })
    return () => setUnauthenticatedHandler(null)
  }, [queryClient])

  const signOut = async () => {
    clearProviderStatusCache()
    try {
      await logout()
    } finally {
      queryClient.clear()
      void queryClient.invalidateQueries({ queryKey: PROVIDER_STATUS_QUERY_KEY })
    }
  }

  if (status.isPending && !status.data) {
    return (
      <main className="min-h-screen grid place-items-center text-sm" role="status">
        Checking your Scriba session…
      </main>
    )
  }

  if (!status.data?.authorized) {
    return <SignIn apiError={status.isError ? status.error : null} status={status.data} />
  }

  const capabilities = capabilitiesFrom(status.data)
  const ready = secretaryReady(status.data)

  return (
    <div className="min-h-screen">
      <header className="flex items-center gap-4 border-b px-5 py-3">
        <h1 className="text-lg font-semibold">Scriba Executive Desk</h1>
        <span className="chip" data-testid="readiness">
          {ready ? 'Ready: mail and calendar connected' : 'Connect a mailbox and a calendar'}
        </span>
        <span className="ml-auto text-sm" data-testid="signed-in-as">
          {status.data.name || status.data.email}
        </span>
        <button type="button" className="btn-secondary" onClick={signOut}>
          Sign out
        </button>
      </header>

      <nav className="flex gap-1 border-b px-5" aria-label="Sections">
        {TABS.map(item => (
          <button
            key={item.id}
            type="button"
            aria-current={tab === item.id ? 'page' : undefined}
            onClick={() => setTab(item.id)}
            className={`px-3 py-2 text-sm border-b-2 ${
              tab === item.id ? 'border-brand-500 font-semibold' : 'border-transparent opacity-70'
            }`}
          >
            <i className={`fas ${item.icon} mr-2`} aria-hidden="true" />
            {item.label}
          </button>
        ))}
      </nav>

      <main className="mx-auto max-w-5xl p-5">
        {tab === 'connections' && <ConnectionsPanel capabilities={capabilities} status={status.data} />}
        {tab === 'inbox' && <InboxPanel capabilities={capabilities} />}
        {tab === 'calendar' && <CalendarPanel capabilities={capabilities} />}
        {tab === 'system' && <SystemPanel />}
      </main>
    </div>
  )
}
