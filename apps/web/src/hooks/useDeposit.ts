'use client'

import { useEffect, useRef, useState } from 'react'
import { getDeposit, DepositResponse } from '../services/financeApi'

const TERMINAL_STATUSES = new Set(['CREDITED', 'FAILED', 'EXPIRED'])
const POLL_INTERVAL_MS = 10_000

export function useDeposit(depositId: string | null, token: string) {
  const [deposit, setDeposit] = useState<DepositResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    if (!depositId) return

    const fetchDeposit = async () => {
      try {
        const d = await getDeposit(depositId, token)
        setDeposit(d)
        if (TERMINAL_STATUSES.has(d.status)) {
          if (intervalRef.current) clearInterval(intervalRef.current)
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error')
      }
    }

    fetchDeposit()
    intervalRef.current = setInterval(fetchDeposit, POLL_INTERVAL_MS)

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [depositId, token])

  return { deposit, error }
}
