'use client'

import Link from 'next/link'
import { useAuthStore } from '@/stores/authStore'
import { useRouter } from 'next/navigation'

export function Header() {
  const { isAuthenticated, user, logout } = useAuthStore()
  const router = useRouter()

  function handleLogout() {
    logout()
    router.push('/login')
  }

  return (
    <header className="h-10 bg-bg-secondary border-b border-border flex items-center justify-end px-4 gap-4 shrink-0">
      {isAuthenticated ? (
        <>
          <span className="text-xs text-text-secondary">{user?.email}</span>
          <button
            onClick={handleLogout}
            className="text-xs text-text-secondary hover:text-text-primary transition-colors"
          >
            Sign out
          </button>
        </>
      ) : (
        <>
          <Link href="/login" className="text-xs text-text-secondary hover:text-text-primary">
            Sign In
          </Link>
          <Link
            href="/register"
            className="text-xs px-3 py-1 bg-accent text-bg-primary rounded font-medium hover:bg-accent/90 transition-colors"
          >
            Register
          </Link>
        </>
      )}
    </header>
  )
}
