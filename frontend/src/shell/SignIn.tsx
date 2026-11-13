import clsx from 'clsx'
import { useState, type FormEvent } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getApiBaseUrl, getErrorMessage, postJson } from '../api/client'
import { googleLoginUrl, microsoftLoginUrl } from '../api/scriba'
import type { ProviderStatusPayload } from '../api/contract'
import { PROVIDER_STATUS_QUERY_KEY } from '../hooks/useProviderStatus'
import { capability } from '../lib/connections'

interface Props {
  /** Set when the API itself could not be reached (not a 401). */
  apiError: unknown
  /** The anonymous provider status, which says what this server can offer. */
  status: ProviderStatusPayload | undefined
}

/**
 * Sign-in uses Scriba's existing identity. Google and Microsoft start with a
 * full-page navigation to the Scriba API host, which owns the registered OAuth
 * callbacks; the Desk never sees a code or a token. Email and password is
 * Scriba's existing POST /auth/signin.
 */
export function SignIn({ apiError, status }: Props) {
  const queryClient = useQueryClient()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const google = capability(status, 'gmail')
  const microsoft = capability(status, 'outlook_mail')

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await postJson('/auth/signin', { email, password })
      await queryClient.invalidateQueries({ queryKey: PROVIDER_STATUS_QUERY_KEY })
    } catch (cause) {
      setError(getErrorMessage(cause, 'Sign-in failed.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="grid min-h-full place-items-center p-5">
      <section className="card w-full max-w-md space-y-4 p-6">
        <div>
          <p className="text-[12px] font-semibold text-accent">Scriba</p>
          <h1 className="text-[22px] font-bold leading-7 text-ink">Scriba Executive Desk</h1>
        </div>
        <p className="text-[13.5px] text-soft">
          Sign in with your existing Scriba account. Your Google and Microsoft
          connections are the ones already authorized in Scriba.
        </p>

        {apiError ? (
          <p role="alert" className="rounded-btn border border-danger/30 bg-danger/[0.08] px-3.5 py-2.5 text-[13px] text-danger">
            The Scriba API at {getApiBaseUrl()} could not be reached: {getErrorMessage(apiError)}
          </p>
        ) : null}

        <div className="grid gap-2">
          <a
            className={clsx('btn btn-primary', google.state === 'unavailable' && 'pointer-events-none opacity-45')}
            href={googleLoginUrl()}
            aria-disabled={google.state === 'unavailable'}
          >
            Continue with Google
          </a>
          <a
            className={clsx('btn btn-secondary', microsoft.state === 'unavailable' && 'pointer-events-none opacity-45')}
            href={microsoftLoginUrl()}
            aria-disabled={microsoft.state === 'unavailable'}
          >
            Continue with Microsoft
          </a>
        </div>
        {google.state === 'unavailable' || microsoft.state === 'unavailable' ? (
          <p className="text-[12px] text-mute">
            {google.state === 'unavailable' ? 'Google sign-in is not configured on this server. ' : ''}
            {microsoft.state === 'unavailable' ? 'Microsoft sign-in is not configured on this server.' : ''}
          </p>
        ) : null}

        <form className="grid gap-2 border-t border-line pt-4" onSubmit={submit}>
          <label className="text-[13px] text-soft" htmlFor="desk-email">Email</label>
          <input
            id="desk-email"
            className="field"
            type="email"
            autoComplete="username"
            value={email}
            onChange={event => setEmail(event.target.value)}
            required
          />
          <label className="text-[13px] text-soft" htmlFor="desk-password">Password</label>
          <input
            id="desk-password"
            className="field"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={event => setPassword(event.target.value)}
            required
          />
          {error ? <p role="alert" className="text-[13px] text-danger">{error}</p> : null}
          <button className="btn btn-secondary" type="submit" disabled={busy}>
            {busy ? 'Signing in…' : 'Sign in with email'}
          </button>
        </form>
      </section>
    </main>
  )
}
