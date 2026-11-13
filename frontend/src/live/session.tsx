import { createContext, useContext } from 'react'
import type { DeskHealthWithPolicy, WritePolicy } from './writePolicy'
import type { LiveDesk, ScribaWorkspace } from './liveDesk'

export interface LiveSession {
  desk: LiveDesk
  workspace: ScribaWorkspace
  /** GET /desk/health, or null while it is loading or when the backend has no Desk overlay. */
  health: DeskHealthWithPolicy | null
  /** ok: the overlay answered. missing: the backend is Scriba without the Desk overlay. error: it could not be asked. */
  overlay: 'checking' | 'ok' | 'missing' | 'error'
  policy: WritePolicy
  signOut: () => Promise<void>
}

const Context = createContext<LiveSession | null>(null)

export const LiveSessionProvider = Context.Provider

/** The live session, or null in demo mode. */
export function useLiveSession(): LiveSession | null {
  return useContext(Context)
}

export function useRequiredLiveSession(): LiveSession {
  const session = useContext(Context)
  if (!session) throw new Error('This screen needs a signed-in Scriba session.')
  return session
}
