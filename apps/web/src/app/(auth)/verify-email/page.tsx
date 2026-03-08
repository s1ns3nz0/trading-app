'use client'

import { useEffect, useState } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'
import Link from 'next/link'

type Status = 'pending' | 'success' | 'error'

export default function VerifyEmailPage() {
  const params = useSearchParams()
  const router = useRouter()
  const token = params.get('token')
  const [status, setStatus] = useState<Status>('pending')

  useEffect(() => {
    if (!token) {
      setStatus('error')
      return
    }

    fetch(`${process.env.NEXT_PUBLIC_IDENTITY_API_URL}/auth/verify-email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    })
      .then((r) => {
        if (r.ok || r.status === 204) {
          setStatus('success')
          setTimeout(() => router.push('/login'), 2500)
        } else {
          setStatus('error')
        }
      })
      .catch(() => setStatus('error'))
  }, [token, router])

  return (
    <div className="bg-bg-secondary border border-border rounded-xl p-8 space-y-4 text-center">
      <h1 className="text-xl font-semibold text-text-primary">Email Verification</h1>

      {status === 'pending' && (
        <p className="text-text-secondary text-sm">Verifying your email address…</p>
      )}

      {status === 'success' && (
        <>
          <p className="text-up font-medium">Email verified successfully!</p>
          <p className="text-text-secondary text-sm">Redirecting to login…</p>
        </>
      )}

      {status === 'error' && (
        <>
          <p className="text-down font-medium">Invalid or expired verification link.</p>
          <p className="text-text-secondary text-sm">
            <Link href="/auth/resend-verification" className="text-accent hover:underline">
              Resend verification email
            </Link>
            {' '}or{' '}
            <Link href="/login" className="text-accent hover:underline">
              back to login
            </Link>
          </p>
        </>
      )}
    </div>
  )
}
