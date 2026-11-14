/**
 * Transferred from Scriba: Gmail/frontend/src/lib/apiBase.ts @ 3ae3a2aa, with one
 * change: backendUrl keeps a path in the base (see there).
 * For the Desk this means: on http://localhost:5173 the API is a local Scriba
 * backend at http://localhost:8000 unless VITE_API_BASE_URL names another
 * host (for example the existing Scriba API host), or a path on the Desk's own
 * origin: the Vercel build sets VITE_API_BASE_URL=/api and proxies /api/* to the
 * API, so the session cookie is first-party in every browser.
 *
 * Backend base-URL discovery — the single source of truth.
 *
 * This module is intentionally **dependency-free**: it imports nothing, not even
 * axios. That is what lets the recovery surfaces (SafeModeApp,
 * MinimalLandingFallback, ErrorBoundary, and the pre-React root-missing
 * fallback in main.tsx) reuse the exact same discovery logic without pulling in
 * the API client, which their own file headers explicitly forbid.
 *
 * `api/client.ts` re-exports `getApiBaseUrl` / `backendUrl` / `redirectToBackend`
 * from here, so there is exactly ONE implementation of this resolution order:
 *
 *   1. VITE_API_BASE_URL, when set at build time (self-hosted / custom API host)
 *   2. localhost + 127.0.0.1  -> same host, port 5173 mapped to 8000
 *   3. scribaassist.com       -> https://api.scribaassist.com  (Scriba SaaS)
 *   4. *.ngrok-*              -> '' (same-origin, tunnels proxy both)
 *   5. api.<host>             -> itself
 *   6. anything else          -> https://api.<bare host>  (the `api.` convention)
 *
 * Previously the recovery surfaces each hardcoded
 * `https://api.scribaassist.com/auth/login`, which sent self-hosted users to
 * Scriba production exactly when their own deployment was failing.
 */

function inferApiBaseUrl(): string {
  const raw = String(import.meta.env.VITE_API_BASE_URL ?? '').trim()
  if (raw) return raw.replace(/\/+$/, '')
  if (typeof window === 'undefined') return ''

  const { protocol, hostname, port } = window.location
  if (!hostname) return ''
  const bareHostname = hostname.startsWith('www.') ? hostname.slice(4) : hostname

  if (hostname === 'localhost' || hostname === '127.0.0.1') {
    const localPort = port === '5173' ? '8000' : (port || '8000')
    return `${protocol}//${hostname}:${localPort}`.replace(/\/+$/, '')
  }

  if (bareHostname === 'scribaassist.com') {
    return 'https://api.scribaassist.com'
  }

  if (
    bareHostname.endsWith('.ngrok-free.dev') ||
    bareHostname.endsWith('.ngrok.app') ||
    bareHostname.endsWith('.ngrok.io')
  ) {
    return ''
  }

  if (hostname.startsWith('api.')) {
    return `${protocol}//${hostname}`.replace(/\/+$/, '')
  }

  return `${protocol}//api.${bareHostname}`.replace(/\/+$/, '')
}

/**
 * Resolved once at module load, matching the previous behaviour in client.ts.
 * Recovery surfaces render after load, so they observe the same value the API
 * client uses.
 */
const normalizedApiBaseUrl = inferApiBaseUrl()

export function isAbsoluteUrl(value: string): boolean {
  return /^https?:\/\//i.test(value)
}

/** The API root, or '/' when the backend is same-origin. */
export function getApiBaseUrl(): string {
  return normalizedApiBaseUrl || '/'
}

/** Raw resolved base (may be ''), for callers that need axios-style baseURL. */
export function getRawApiBaseUrl(): string {
  return normalizedApiBaseUrl
}

/**
 * URL for a backend path, honouring the discovery order above. The path is appended to the base,
 * so a base with a path keeps it: base '/api' gives '/api/auth/login' (relative, same origin) and
 * 'https://host/api' gives 'https://host/api/auth/login'. Resolving with `new URL(path, base)`, as
 * Scriba does, would drop '/api' because the path starts with '/', and throws on a relative base.
 */
export function backendUrl(path = '/'): string {
  if (!path) return normalizedApiBaseUrl || '/'
  if (isAbsoluteUrl(path)) return path
  if (!normalizedApiBaseUrl) return path
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${normalizedApiBaseUrl}${normalizedPath}`
}

/** Same as backendUrl, minus the scheme — for user-facing link text. */
export function backendUrlLabel(path = '/'): string {
  return backendUrl(path).replace(/^https?:\/\//i, '').replace(/\/+$/, '')
}

export function redirectToBackend(path: string): void {
  window.location.href = backendUrl(path)
}
