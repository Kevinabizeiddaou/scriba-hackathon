import { createContext, useContext } from 'react'
import type { DeskSandbox } from '../api/desk'
import type { DeskMode } from './executionMode'
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
  /** What an approval does on this backend, from GET /desk/health. Drives every sandbox and live marker. */
  mode: DeskMode
  /** The caller's sandbox world (GET /desk/sandbox). Null outside a sandbox, or while it loads. */
  sandbox: DeskSandbox | null
  /**
   * Where the time zone on screen comes from. `executive`: the backend named the executive's zone.
   * `browser`: it has not (yet), and times are in this browser's zone, which the screens say.
   */
  timeZoneSource: 'executive' | 'browser'
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
