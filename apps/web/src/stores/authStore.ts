import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { User, AuthTokens } from '@trading/types'

interface AuthState {
  user: User | null
  tokens: AuthTokens | null
  isAuthenticated: boolean
  login: (tokens: AuthTokens, user: User) => void
  logout: () => void
  updateUser: (update: Partial<User>) => void
  refreshTokens: (tokens: AuthTokens) => void
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set) => ({
      user: null,
      tokens: null,
      isAuthenticated: false,

      login: (tokens, user) => set({ tokens, user, isAuthenticated: true }),

      logout: () => set({ user: null, tokens: null, isAuthenticated: false }),

      updateUser: (update) =>
        set((state) => ({
          user: state.user ? { ...state.user, ...update } : null,
        })),

      refreshTokens: (tokens) => set({ tokens }),
    }),
    {
      name: 'auth-storage',
      // Access token stays in memory only (never persisted).
      // The refresh token is an httpOnly cookie set by the identity service
      // via Set-Cookie — it is never readable from JS and therefore not stored here.
      // Only non-sensitive user profile data is persisted for UX continuity.
      partialize: (state) => ({ user: state.user }),
      onRehydrateStorage: () => (state) => {
        if (state?.user) {
          // isAuthenticated will be re-confirmed after the silent token refresh
          // that happens on app boot; keep false until tokens are in memory.
          state.isAuthenticated = false
        }
      },
    },
  ),
)
