/**
 * Transferred from Scriba: Gmail/frontend/src/api/client.ts @ 3ae3a2aa.
 * Changed for the Desk: the 401 interceptor no longer redirects into a
 * provider OAuth flow (see setUnauthenticatedHandler). Everything else,
 * including `withCredentials: true` (the session is an HttpOnly cookie owned
 * by the API host) and the error normalisation, is unchanged.
 */
import axios, { AxiosError, type AxiosRequestConfig } from 'axios'
import {
  backendUrl,
  getApiBaseUrl,
  getRawApiBaseUrl,
  redirectToBackend,
} from '../lib/apiBase'

export class ApiClientError extends Error {
  status?: number
  code?: string
  details?: unknown
  requestId?: string

  constructor(message: string, options?: {
    status?: number
    code?: string
    details?: unknown
    requestId?: string
  }) {
    super(message)
    this.name = 'ApiClientError'
    this.status = options?.status
    this.code = options?.code
    this.details = options?.details
    this.requestId = options?.requestId
  }
}

// Backend base-URL discovery lives in lib/apiBase.ts so the dependency-light
// recovery surfaces (safe mode, error/landing fallbacks) can reuse the exact
// same logic without importing this module and its axios dependency. These
// re-exports keep the existing `from '../api/client'` import sites working.
export { getApiBaseUrl, backendUrl, redirectToBackend }

const normalizedApiBaseUrl = getRawApiBaseUrl()
const isDev = Boolean(import.meta.env.DEV)

const api = axios.create({
  baseURL: normalizedApiBaseUrl || '/',
  withCredentials: true,
  // No global timeout: uploads and full syncs can legitimately run long. The
  // chat POST sets its own bound (see postChatMessage) so the "thinking" bubble
  // can't spin forever on a hung backend.
})

function normalizeError(error: unknown): ApiClientError {
  if (error instanceof ApiClientError) return error

  const axiosError = error as AxiosError<{
    error?: string
    detail?: string
    errorCode?: string
    details?: unknown
    requestId?: string
  }>
  const data = axiosError.response?.data
  const message =
    data?.error ||
    data?.detail ||
    axiosError.message ||
    'Request failed.'

  return new ApiClientError(message, {
    status: axiosError.response?.status,
    code: data?.errorCode,
    details: data?.details ?? (
      isDev
        ? {
            requestUrl: axiosError.config?.url,
            resolvedUrl: axiosError.config?.url ? backendUrl(String(axiosError.config.url)) : undefined,
            apiBaseUrl: getApiBaseUrl(),
            method: axiosError.config?.method,
          }
        : undefined
    ),
    requestId: data?.requestId,
  })
}

// Auth endpoints whose 401 is a form error, not a lost session.
const AUTH_FORM_PATHS = ['/auth/signin', '/auth/register']

let unauthenticatedHandler: (() => void) | null = null

/** Register what happens when the API says the session is gone (401). */
export function setUnauthenticatedHandler(handler: (() => void) | null) {
  unauthenticatedHandler = handler
}

api.interceptors.response.use(
  response => response,
  error => {
    const axiosError = error as AxiosError
    if (isDev) {
      const requestUrl = String(axiosError.config?.url ?? '')
      console.error('API request failed', {
        method: axiosError.config?.method,
        requestUrl,
        resolvedUrl: requestUrl ? backendUrl(requestUrl) : undefined,
        apiBaseUrl: getApiBaseUrl(),
        status: axiosError.response?.status,
        message: axiosError.message,
      })
    }
    if (axiosError.response?.status === 401) {
      const url = String(axiosError.config?.url ?? '')
      // Desk change: Scriba's client redirected straight into an OAuth flow
      // here (Jira, Slack, Teams, Outlook or Google by URL prefix). The Desk
      // has two identity providers and no excluded ones, so a lost session
      // returns the user to the sign-in screen, where THEY choose Google or
      // Microsoft. Nothing navigates on its own.
      if (!AUTH_FORM_PATHS.some(p => url.includes(p))) {
        unauthenticatedHandler?.()
      }
    }
    return Promise.reject(normalizeError(error))
  },
)

export function getErrorMessage(error: unknown, fallback = 'Something went wrong.') {
  if (error instanceof ApiClientError) return error.message
  if (error instanceof Error) return error.message
  if (typeof error === 'string' && error.trim()) return error
  return fallback
}

export async function getJson<T>(url: string, config?: AxiosRequestConfig) {
  const response = await api.get<T>(url, config)
  return response.data
}

export async function postJson<T>(url: string, data?: unknown, config?: AxiosRequestConfig) {
  const response = await api.post<T>(url, data, config)
  return response.data
}

export async function patchJson<T>(url: string, data?: unknown, config?: AxiosRequestConfig) {
  const response = await api.patch<T>(url, data, config)
  return response.data
}

export async function putJson<T>(url: string, data?: unknown, config?: AxiosRequestConfig) {
  const response = await api.put<T>(url, data, config)
  return response.data
}

export async function deleteJson<T>(url: string, config?: AxiosRequestConfig) {
  const response = await api.delete<T>(url, config)
  return response.data
}

export async function postForm<T>(url: string, data: FormData, config?: AxiosRequestConfig) {
  const response = await api.post<T>(url, data, {
    ...config,
    headers: {
      'Content-Type': 'multipart/form-data',
      ...(config?.headers ?? {}),
    },
  })
  return response.data
}

export default api
