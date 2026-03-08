import { useAuthStore } from '@/stores/authStore'
import type { AuthTokens } from '@trading/types'

type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH'

interface RequestOptions {
  method?: HttpMethod
  body?: unknown
  authenticated?: boolean
}

// Per-service base URLs (each domain has its own AWS account / endpoint)
export const SPOT_API = process.env.NEXT_PUBLIC_SPOT_API_URL ?? 'http://localhost:8001'
export const FUTURES_API = process.env.NEXT_PUBLIC_FUTURES_API_URL ?? 'http://localhost:8002'
export const FINANCE_API = process.env.NEXT_PUBLIC_FINANCE_API_URL ?? 'http://localhost:8003'
export const IDENTITY_API = process.env.NEXT_PUBLIC_IDENTITY_API_URL ?? 'http://localhost:8000'

/**
 * Silent token refresh — sends the httpOnly refresh_token cookie to /auth/refresh.
 * The cookie is managed by the browser and never accessible from JS.
 */
async function silentRefresh(): Promise<AuthTokens> {
  const response = await fetch(`${IDENTITY_API}/auth/refresh`, {
    method: 'POST',
    credentials: 'include',  // sends httpOnly cookie
  })
  if (!response.ok) throw new Error('Refresh failed')
  const data = await response.json()
  // Backend returns { access_token, token_type } — map to camelCase
  return { accessToken: data.access_token, tokenType: data.token_type }
}

async function request<T>(baseUrl: string, path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, authenticated = true } = options

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }

  if (authenticated) {
    const tokens = useAuthStore.getState().tokens
    if (!tokens) throw new Error('NOT_AUTHENTICATED')
    headers['Authorization'] = `Bearer ${tokens.accessToken}`
  }

  const response = await fetch(`${baseUrl}${path}`, {
    method,
    headers,
    credentials: 'include',  // required for httpOnly refresh_token cookie
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

  if (response.status === 401 && authenticated) {
    // Attempt silent token refresh before logging out
    try {
      const newTokens = await silentRefresh()
      useAuthStore.getState().refreshTokens(newTokens)
      // Retry original request with new access token
      headers['Authorization'] = `Bearer ${newTokens.accessToken}`
      const retryResponse = await fetch(`${baseUrl}${path}`, {
        method,
        headers,
        credentials: 'include',
        body: body !== undefined ? JSON.stringify(body) : undefined,
      })
      if (retryResponse.ok) {
        if (retryResponse.status === 204) return undefined as T
        return retryResponse.json() as Promise<T>
      }
    } catch {
      // Refresh failed — session is truly expired
    }
    useAuthStore.getState().logout()
    throw new Error('SESSION_EXPIRED')
  }

  if (!response.ok) {
    const errorData = (await response.json().catch(() => null)) as { detail?: string; message?: string } | null
    throw new Error(errorData?.detail ?? errorData?.message ?? `HTTP ${response.status}`)
  }

  // 204 No Content
  if (response.status === 204) return undefined as T

  return response.json() as Promise<T>
}

export const spotRequest = <T>(path: string, opts?: RequestOptions) =>
  request<T>(SPOT_API, path, opts)

export const futuresRequest = <T>(path: string, opts?: RequestOptions) =>
  request<T>(FUTURES_API, path, opts)

export const financeRequest = <T>(path: string, opts?: RequestOptions) =>
  request<T>(FINANCE_API, path, opts)

export const identityRequest = <T>(path: string, opts?: RequestOptions) =>
  request<T>(IDENTITY_API, path, opts)
