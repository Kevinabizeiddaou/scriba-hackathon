// Transferred from Scriba: Gmail/frontend/src/hooks/useProviderStatus.ts @ 3ae3a2aa.
// Changed for the Desk: import paths, and a Desk-specific cache key so the two
// apps never read each other's cached snapshot on a shared origin.
import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { fetchProviderStatus } from '../api/scriba'
import type { ProviderStatusPayload } from '../api/contract'

export const PROVIDER_STATUS_QUERY_KEY = ['provider-status'] as const

// The whole app gates first paint on provider-status. On a page reload the
// in-memory query cache is empty, so without this the user stares at a
// full-screen spinner for the entire (sometimes slow) round-trip. We persist
// the last snapshot in localStorage and seed it as initialData so the app
// renders instantly from cache, then revalidates in the background
// (stale-while-revalidate). No tokens/secrets live in this payload — just
// connection state and display info that's already in the DOM.
const CACHE_KEY = 'scriba-desk.provider-status.v1'

function readCache(): ProviderStatusPayload | undefined {
  try {
    const raw = window.localStorage.getItem(CACHE_KEY)
    return raw ? (JSON.parse(raw) as ProviderStatusPayload) : undefined
  } catch {
    return undefined
  }
}

// Drop the persisted snapshot synchronously. Must be called on logout and
// account switch: otherwise the next reload seeds the app from the previous
// user's (still-authorized) snapshot and flashes their authenticated shell —
// and their email/connection state — before the background revalidate lands.
// The persist effect below only clears on an unauthorized *fetch*, which this
// change deliberately moved off the reload critical path, so an explicit purge
// is required here.
export function clearProviderStatusCache() {
  try {
    window.localStorage.removeItem(CACHE_KEY)
  } catch {
    /* storage unavailable — best-effort */
  }
}

export function useProviderStatus() {
  const query = useQuery({
    queryKey: PROVIDER_STATUS_QUERY_KEY,
    queryFn: fetchProviderStatus,
    staleTime: 60_000,
    retry: false,
    // Seed from the persisted snapshot so a reload paints immediately.
    initialData: readCache,
    // ...marked always-stale so a reload still revalidates in the background
    // (non-blocking) and the data never drifts.
    initialDataUpdatedAt: 0,
  })

  // Persist only real network results — never the seeded snapshot — so the
  // cache reflects the server's latest truth. When a fetch comes back
  // unauthorized (logout / expired session) we drop the snapshot so the next
  // reload lands on the sign-in page instead of flashing a stale shell.
  useEffect(() => {
    if (!query.isFetchedAfterMount) return
    try {
      if (query.data?.authorized) {
        window.localStorage.setItem(CACHE_KEY, JSON.stringify(query.data))
      } else if (query.isSuccess) {
        window.localStorage.removeItem(CACHE_KEY)
      }
    } catch {
      /* storage unavailable — caching is best-effort */
    }
  }, [query.data, query.isSuccess, query.isFetchedAfterMount])

  return query
}
