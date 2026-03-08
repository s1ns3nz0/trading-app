/**
 * initializeAuth — called once on app boot.
 *
 * If a persisted user exists in the store (from a previous session),
 * attempts a silent token refresh via the httpOnly refresh_token cookie.
 * On success: restores the access token and marks isAuthenticated = true.
 * On failure: clears store (user must log in again).
 */

import { useAuthStore } from '@/stores/authStore'
import { IDENTITY_API } from '@/services/api'
import type { AuthTokens } from '@trading/types'

async function silentRefresh(): Promise<AuthTokens> {
  const response = await fetch(`${IDENTITY_API}/auth/refresh`, {
    method: 'POST',
    credentials: 'include',
  })
  if (!response.ok) throw new Error('Refresh failed')
  const data = await response.json()
  return { accessToken: data.access_token, tokenType: data.token_type }
}

export async function initializeAuth(): Promise<void> {
  const { user, refreshTokens } = useAuthStore.getState()

  // No persisted user — nothing to restore
  if (!user) return

  try {
    const tokens = await silentRefresh()
    refreshTokens(tokens)
    useAuthStore.setState({ isAuthenticated: true })
  } catch {
    // Refresh token expired or invalid — force re-login
    useAuthStore.getState().logout()
  }
}
