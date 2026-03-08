'use client'

import { useCallback, useEffect, useRef } from 'react'
import { useWebSocket } from './useWebSocket'
import { useTradingStore } from '@/stores/tradingStore'
import type { WsTickerMessage } from '@trading/types'

// API Gateway WebSocket uses a single connection + subscribe/unsubscribe actions.
// The URL is the root stage endpoint (no path).
const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? ''

export function useTicker(symbol: string) {
  const { ticker, setTicker } = useTradingStore()
  const sendRef = useRef<((data: unknown) => void) | null>(null)

  const handleMessage = useCallback(
    (data: unknown) => {
      const msg = data as WsTickerMessage
      if (msg.type === 'ticker' && msg.symbol === symbol) {
        setTicker(msg.data)
      }
    },
    [setTicker, symbol],
  )

  const handleOpen = useCallback(() => {
    // Subscribe after connection is established
    sendRef.current?.({ action: 'subscribe', channel: 'ticker', symbol })
  }, [symbol])

  const { status, send } = useWebSocket(WS_URL, {
    onMessage: handleMessage,
    onOpen: handleOpen,
    enabled: Boolean(WS_URL),
  })

  // Keep sendRef up to date without creating a new connect
  useEffect(() => {
    sendRef.current = send
  }, [send])

  // Resubscribe when symbol changes
  useEffect(() => {
    if (status === 'open') {
      send({ action: 'subscribe', channel: 'ticker', symbol })
    }
    return () => {
      if (status === 'open') {
        send({ action: 'unsubscribe', channel: 'ticker', symbol })
      }
    }
  }, [symbol, status, send])

  return { ticker }
}
