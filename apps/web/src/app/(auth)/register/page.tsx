'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { register } from '@/services/identityApi'
import { useAuthStore } from '@/stores/authStore'

export default function RegisterPage() {
  const router = useRouter()
  const { login: storeLogin } = useAuthStore()

  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [isLoading, setIsLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (password !== confirm) {
      setError('Passwords do not match')
      return
    }
    setError('')
    setIsLoading(true)

    try {
      const result = await register({ email, username, password })
      storeLogin(result.tokens, result.user)
      router.push('/spot/BTC-USDT')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Registration failed')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="bg-bg-secondary border border-border rounded-xl p-8 space-y-6">
      <h1 className="text-xl font-semibold text-text-primary">Create Account</h1>

      {error && (
        <div className="px-4 py-3 bg-down/10 border border-down/30 rounded text-down text-sm">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-4">
        {[
          { label: 'Email', value: email, setter: setEmail, type: 'email', autocomplete: 'email' },
          { label: 'Username', value: username, setter: setUsername, type: 'text', autocomplete: 'username' },
          { label: 'Password', value: password, setter: setPassword, type: 'password', autocomplete: 'new-password' },
          { label: 'Confirm Password', value: confirm, setter: setConfirm, type: 'password', autocomplete: 'new-password' },
        ].map(({ label, value, setter, type, autocomplete }) => (
          <div key={label}>
            <label className="block text-sm text-text-secondary mb-1.5">{label}</label>
            <input
              type={type}
              value={value}
              onChange={(e) => setter(e.target.value)}
              required
              autoComplete={autocomplete}
              className="w-full bg-bg-tertiary border border-border rounded-lg px-4 py-2.5 text-text-primary text-sm outline-none focus:border-accent transition-colors"
            />
          </div>
        ))}

        <button
          type="submit"
          disabled={isLoading}
          className="w-full bg-accent text-bg-primary font-semibold py-2.5 rounded-lg hover:bg-accent/90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isLoading ? 'Creating account…' : 'Create Account'}
        </button>
      </form>

      <p className="text-center text-sm text-text-secondary">
        Already have an account?{' '}
        <Link href="/login" className="text-accent hover:underline">
          Sign In
        </Link>
      </p>
    </div>
  )
}
