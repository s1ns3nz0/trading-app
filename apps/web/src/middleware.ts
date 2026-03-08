import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

/**
 * Route protection middleware.
 *
 * Uses the presence of the `refresh_token` httpOnly cookie as a proxy
 * for "has an active session" — the access token is memory-only and
 * not accessible in middleware (Edge runtime).
 *
 * On missing cookie: redirect unauthenticated users to /login.
 * Auth pages (/login, /register, /auth/*) are always public.
 */

const PUBLIC_PATHS = [
  '/login',
  '/register',
  '/auth',   // covers /auth/verify-email, /auth/resend-verification, etc.
]

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl

  // Allow public paths without auth check
  const isPublic = PUBLIC_PATHS.some((p) => pathname.startsWith(p))
  if (isPublic) return NextResponse.next()

  // Check for refresh_token cookie as session indicator
  const hasSession = request.cookies.has('refresh_token')
  if (!hasSession) {
    const loginUrl = new URL('/login', request.url)
    loginUrl.searchParams.set('redirect', pathname)
    return NextResponse.redirect(loginUrl)
  }

  return NextResponse.next()
}

export const config = {
  // Apply middleware to all routes except Next.js internals and static files
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico|.*\\.png$).*)'],
}
