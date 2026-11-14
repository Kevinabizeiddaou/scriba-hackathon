import { afterEach, describe, expect, it, vi } from 'vitest'

// apiBase resolves its base once, at module load, so each case loads a fresh copy.
async function loadWithBase(base: string) {
  vi.stubEnv('VITE_API_BASE_URL', base)
  vi.resetModules()
  return import('./apiBase')
}

afterEach(() => {
  vi.unstubAllEnvs()
  vi.resetModules()
})

describe('backendUrl', () => {
  it('keeps a same-origin path base, as the Vercel /api proxy needs', async () => {
    const { backendUrl, getApiBaseUrl } = await loadWithBase('/api')
    expect(getApiBaseUrl()).toBe('/api')
    expect(backendUrl('/auth/login')).toBe('/api/auth/login')
    expect(backendUrl('desk/inbox')).toBe('/api/desk/inbox')
  })

  it('keeps a path on an absolute base', async () => {
    const { backendUrl } = await loadWithBase('https://desk.example.com/api/')
    expect(backendUrl('/emails')).toBe('https://desk.example.com/api/emails')
  })

  it('is unchanged for an API at a host root', async () => {
    const { backendUrl } = await loadWithBase('https://api.example.com')
    expect(backendUrl('/oauth/callback')).toBe('https://api.example.com/oauth/callback')
    expect(backendUrl('https://other.example.com/x')).toBe('https://other.example.com/x')
  })

  it('still maps the local dev origin to port 8000 when no base is set', async () => {
    const { backendUrl } = await loadWithBase('')
    expect(backendUrl('/auth/login')).toBe('http://localhost:8000/auth/login')
  })
})
