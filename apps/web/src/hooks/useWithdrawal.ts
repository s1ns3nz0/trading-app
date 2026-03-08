'use client'

import { useEffect, useRef, useState } from 'react'
import { getWithdrawalById, WithdrawalResponse } from '../services/financeApi'

const TERMINAL_STATUSES = new Set(['EXECUTED', 'REJECTED', 'FAILED', 'CANCELLED'])
const POLL_INTERVAL_MS = 10_000

export function useWithdrawal(withdrawalId: string | null, token: string) {
  const [withdrawal, setWithdrawal] = useState<WithdrawalResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    if (!withdrawalId) return

    const fetchWithdrawal = async () => {
      try {
        const w = await getWithdrawalById(withdrawalId, token)
        setWithdrawal(w)
        if (TERMINAL_STATUSES.has(w.status)) {
          if (intervalRef.current) clearInterval(intervalRef.current)
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error')
      }
    }

    fetchWithdrawal()
    intervalRef.current = setInterval(fetchWithdrawal, POLL_INTERVAL_MS)
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [withdrawalId, token])

  return { withdrawal, error }
}
