'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { useWebSocket } from './useWebSocket'
import { useTradingStore } from '@/stores/tradingStore'
import type { WsOrderBookMessage } from '@trading/types'

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? ''

export function useOrderBook(symbol: string) {
  const { orderBook, updateOrderBook } = useTradingStore()
  const [isLoading, setIsLoading] = useState(true)
  const sendRef = useRef<((data: unknown) => void) | null>(null)

  const handleMessage = useCallback(
    (data: unknown) => {
      const msg = data as WsOrderBookMessage
      if (msg.type === 'orderbook' && msg.symbol === symbol) {
        updateOrderBook(msg.data)
        setIsLoading(false)
      }
    },
    [updateOrderBook, symbol],
  )

  const handleOpen = useCallback(() => {
    sendRef.current?.({ action: 'subscribe', channel: 'orderbook', symbol })
  }, [symbol])

  const { status, send } = useWebSocket(WS_URL, {
    onMessage: handleMessage,
    onOpen: handleOpen,
    onClose: () => setIsLoading(true),
    enabled: Boolean(WS_URL),
  })

  useEffect(() => {
    sendRef.current = send
  }, [send])

  useEffect(() => {
    if (status === 'open') {
      send({ action: 'subscribe', channel: 'orderbook', symbol })
    }
    return () => {
      if (status === 'open') {
        send({ action: 'unsubscribe', channel: 'orderbook', symbol })
      }
    }
  }, [symbol, status, send])

  return { orderBook, isLoading, wsStatus: status }
}
