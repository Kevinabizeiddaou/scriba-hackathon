import { useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiClientError, getApiBaseUrl, setUnauthenticatedHandler } from '../api/client'
import { fetchDeskBriefing, fetchDeskHealth, fetchDeskSandbox } from '../api/desk'
import { logout } from '../api/scriba'
import { ShellBadgesContext, type ShellBadges } from '../components/AppShell'
import { setApi } from '../harness'
import { PROVIDER_STATUS_QUERY_KEY, clearProviderStatusCache, useProviderStatus } from '../hooks/useProviderStatus'
import { SignIn } from '../shell/SignIn'
import { deskModeFrom } from './executionMode'
import { LiveDesk, ScribaWorkspace } from './liveDesk'
import { LiveRoutes } from './LiveRoutes'
import { useWorkQueue } from './LiveWorkPages'
import { deskIndexOf, partitionCards } from './ownership'
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

  const mode = useMemo(() => deskModeFrom(health.data, overlay), [health.data, overlay])
  // The sandbox world: its clock, its accounts and everything executed in it. Asked only in a sandbox.
  const sandbox = useQuery({ queryKey: SANDBOX_KEY, queryFn: fetchDeskSandbox, enabled: mode.kind === 'sandbox', retry: false, refetchInterval: 30_000 })
  const world = mode.kind === 'sandbox' ? sandbox.data?.world ?? null : null
  // The sandbox screens (calendar, tasks) read the world instead of Scriba's own stores.
  useEffect(() => {
    workspace.setSandbox(mode.kind === 'sandbox')
  }, [workspace, mode.kind])
  // A world with a fixed clock has its own "today"; the screens follow it instead of the browser's.
  useEffect(() => {
    desk.setSimulatedNow(world?.fixedClock ? world.now : null)
  }, [desk, world?.fixedClock, world?.now])

  // The executive's time zone is on the briefing (in a sandbox: the world's zone). It is asked for
  // once per session, whichever screen opens first, so no screen falls back to the browser's zone
  // just because the overview was not visited. The overview reads the same cached answer.
  const briefing = useQuery({ queryKey: ['desk', 'briefing'], queryFn: fetchDeskBriefing, enabled: overlay === 'ok', staleTime: 30_000 })
  useEffect(() => {
    desk.setTimeZone(briefing.data?.timezone)
  }, [briefing.data?.timezone, desk])
  // Re-render when the desk learns the zone, so every time on screen moves to it together.
  const info = useSyncExternalStore(listener => desk.subscribe(listener), () => desk.info)

  const session = useMemo<LiveSession>(
    () => ({
      desk,
      workspace,
      health: health.data ?? null,
      overlay,
      policy: writePolicyFrom(health.data),
      mode,
      sandbox: world,
      timeZoneSource: desk.timeZoneSource,
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [desk, workspace, health.data, overlay, queryClient, mode, world, info],
  )

  return (
    <LiveSessionProvider value={session}>
      <WithBadges>
        <LiveRoutes />
      </WithBadges>
    </LiveSessionProvider>
  )
}

export const SANDBOX_KEY = ['desk', 'sandbox'] as const

/** Counts for the navigation, from the same action records the approval center shows. */
function WithBadges({ children }: { children: React.ReactNode }) {
  const queue = useWorkQueue()
  // Desk runs exist only with the overlay; without it the work queue has no badge and no request.
  const session = useRequiredLiveSession()
  const runs = useRunQueue(session.overlay === 'ok')
  const badges = useMemo<ShellBadges>(() => {
    const all = queue.data?.cards.filter(isWorkItem)
    // The secretary's numbers count the Desk's own cards. Cards from Scriba's chat are listed
    // apart in the approval center and are not in the badge. Without the overlay there are no
    // Desk runs, and every card counts as before.
    const overlayOk = session.overlay === 'ok'
    const work = all && overlayOk ? (runs.data ? partitionCards(all, deskIndexOf(runs.data)).desk : null) : all
    return {
      approvals: work ? work.filter(needsUser).length : null,
      problems: work ? work.filter(needsIntervention).length : null,
      work: runsNeedingUser(runs.data),
    }
  }, [queue.data, runs.data, session.overlay])
  return <ShellBadgesContext.Provider value={badges}>{children}</ShellBadgesContext.Provider>
}
