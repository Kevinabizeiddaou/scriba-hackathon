import { useEffect, useMemo, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiClientError, getApiBaseUrl, setUnauthenticatedHandler } from '../api/client'
import { fetchDeskHealth } from '../api/desk'
import { logout } from '../api/scriba'
import { ShellBadgesContext, type ShellBadges } from '../components/AppShell'
import { setApi } from '../harness'
import { PROVIDER_STATUS_QUERY_KEY, clearProviderStatusCache, useProviderStatus } from '../hooks/useProviderStatus'
import { SignIn } from '../shell/SignIn'
import { LiveDesk, ScribaWorkspace } from './liveDesk'
import { LiveRoutes } from './LiveRoutes'
import { useWorkQueue } from './LiveWorkPages'
import { runsNeedingUser, useRunQueue } from './LiveWorkQueuePage'
import { LiveSessionProvider, useRequiredLiveSession, type LiveSession } from './session'
import { isWorkItem, needsIntervention, needsUser } from './workQueue'
import { writePolicyFrom, type DeskHealthWithPolicy } from './writePolicy'

/**
 * The session gate. Authentication is Scriba's: the HttpOnly session cookie, read through
 * GET /providers/status. There is no token and no second sign-in. A 401 from any request drops
 * the cached status and returns to the sign-in screen, where the user chooses how to sign in;
 * nothing navigates to a provider on its own.
 */
export function LiveApp() {
  const queryClient = useQueryClient()
  const status = useProviderStatus()

  useEffect(() => {
    setUnauthenticatedHandler(() => {
      clearProviderStatusCache()
      void queryClient.invalidateQueries({ queryKey: PROVIDER_STATUS_QUERY_KEY })
    })
    return () => setUnauthenticatedHandler(null)
  }, [queryClient])

  if (status.isPending && !status.data) {
    return (
      <main className="grid h-full place-items-center text-[13px] text-soft" role="status">
        Checking your Scriba session…
      </main>
    )
  }

  if (!status.data?.authorized) {
    // Signed out: the screens must not keep an implementation bound to the previous user.
    setApi(null)
    return <SignIn apiError={status.isError ? status.error : null} status={status.data} />
  }

  return <SignedIn key={status.data.email ?? 'user'} email={status.data.email} name={status.data.name ?? null} />
}

function SignedIn({ email, name }: { email: string | null; name: string | null }) {
  const queryClient = useQueryClient()

  // One desk and one workspace per signed-in user. A different user gets new ones (the key above),
  // so nothing read for one account is ever shown to another.
  const [{ desk, workspace }] = useState(() => {
    const desk = new LiveDesk({ email, name }, getApiBaseUrl())
    return { desk, workspace: new ScribaWorkspace(desk) }
  })
  // Installed on every render: an assignment, so it is safe under StrictMode's double render.
  setApi(desk, workspace)

  const health = useQuery<DeskHealthWithPolicy>({ queryKey: ['desk', 'health'], queryFn: fetchDeskHealth, retry: false, staleTime: 60_000 })
  const overlay: LiveSession['overlay'] = health.isPending
    ? 'checking'
    : health.isSuccess
      ? 'ok'
      : health.error instanceof ApiClientError && health.error.status === 404
        ? 'missing'
        : 'error'

  const session = useMemo<LiveSession>(
    () => ({
      desk,
      workspace,
      health: health.data ?? null,
      overlay,
      policy: writePolicyFrom(health.data),
      signOut: async () => {
        clearProviderStatusCache()
        try {
          await logout()
        } finally {
          // Drop everything read for this user, then ask Scriba again who is signed in. The status
          // query is reset rather than removed: a mounted query that is removed is never refetched,
          // and the screen would go on showing the signed-in workspace.
          queryClient.removeQueries({ predicate: query => query.queryKey[0] !== PROVIDER_STATUS_QUERY_KEY[0] })
          await queryClient.resetQueries({ queryKey: PROVIDER_STATUS_QUERY_KEY })
        }
      },
    }),
    [desk, workspace, health.data, overlay, queryClient],
  )

  return (
    <LiveSessionProvider value={session}>
      <WithBadges>
        <LiveRoutes />
      </WithBadges>
    </LiveSessionProvider>
  )
}

/** Counts for the navigation, from the same action records the approval center shows. */
function WithBadges({ children }: { children: React.ReactNode }) {
  const queue = useWorkQueue()
  // Desk runs exist only with the overlay; without it the work queue has no badge and no request.
  const runs = useRunQueue(useRequiredLiveSession().overlay === 'ok')
  const badges = useMemo<ShellBadges>(() => {
    const work = queue.data?.cards.filter(isWorkItem)
    return {
      approvals: work ? work.filter(needsUser).length : null,
      problems: work ? work.filter(needsIntervention).length : null,
      work: runsNeedingUser(runs.data),
    }
  }, [queue.data, runs.data])
  return <ShellBadgesContext.Provider value={badges}>{children}</ShellBadgesContext.Provider>
}
