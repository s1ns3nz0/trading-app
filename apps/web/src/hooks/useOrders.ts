'use client'

import { useEffect, useCallback, useRef } from 'react'
import { useWebSocket } from './useWebSocket'
import { useTradingStore } from '@/stores/tradingStore'
import { useAuthStore } from '@/stores/authStore'
import { getOpenOrders } from '@/services/spotTradingApi'
import type { WsOrderUpdateMessage } from '@trading/types'

export function useOrders(symbol: string) {
  const { openOrders, setOpenOrders, updateOrder } = useTradingStore()
  const { isAuthenticated, tokens } = useAuthStore()

  // Fetch initial open orders via REST
  useEffect(() => {
    if (!isAuthenticated) return
    getOpenOrders(symbol).then(setOpenOrders).catch(console.error)
  }, [symbol, isAuthenticated, setOpenOrders])

  // Subscribe to order updates via WebSocket
  const wsUrl = `${process.env.NEXT_PUBLIC_WS_URL}/user/orders`

  const handleMessage = useCallback(
    (data: unknown) => {
      const msg = data as WsOrderUpdateMessage
      if (msg.type === 'order_update') {
        updateOrder(msg.data)
      }
    },
    [updateOrder],
  )

  // sendRef breaks the circular dependency between onOpen and send:
  // onOpen needs send, but send comes from useWebSocket which needs onOpen.
  // useWebSocket calls onOpen via optionsRef (always up-to-date), so reading
  // sendRef.current at call time is safe.
  const sendRef = useRef<((data: unknown) => void) | null>(null)

  const handleOpen = useCallback(() => {
    // Send auth handshake immediately after connection opens.
    // The server requires { type: "auth", token: "<accessToken>" } before
    // it will stream order updates for this user.
    const accessToken = useAuthStore.getState().tokens?.accessToken
    if (accessToken && sendRef.current) {
      sendRef.current({ type: 'auth', token: accessToken })
    }
  }, [])

  const { send } = useWebSocket(wsUrl, {
    onMessage: handleMessage,
    onOpen: handleOpen,
    enabled: isAuthenticated && !!tokens,
  })

  // Keep ref in sync so handleOpen always calls the latest send
  sendRef.current = send

  return { openOrders }
}
