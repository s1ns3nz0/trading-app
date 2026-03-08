'use client'

import { useEffect, useRef, useCallback, useState } from 'react'

export type WsStatus = 'connecting' | 'open' | 'closed' | 'error'

interface UseWebSocketOptions {
  onMessage: (data: unknown) => void
  onOpen?: () => void
  onClose?: () => void
  reconnectInterval?: number
  maxReconnectAttempts?: number
  enabled?: boolean
}

export function useWebSocket(url: string, options: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectCountRef = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout>>()
  const [status, setStatus] = useState<WsStatus>('connecting')
  const optionsRef = useRef(options)
  optionsRef.current = options

  const {
    reconnectInterval = 3000,
    maxReconnectAttempts = 5,
    enabled = true,
  } = options

  const connect = useCallback(() => {
    if (!enabled || wsRef.current?.readyState === WebSocket.OPEN) return

    const ws = new WebSocket(url)
    wsRef.current = ws
    setStatus('connecting')

    ws.onopen = () => {
      setStatus('open')
      reconnectCountRef.current = 0
      optionsRef.current.onOpen?.()
    }

    ws.onmessage = (event) => {
      try {
        const data: unknown = JSON.parse(event.data as string)
        optionsRef.current.onMessage(data)
      } catch {
        // ignore non-JSON
      }
    }

    ws.onerror = () => {
      setStatus('error')
    }

    ws.onclose = () => {
      setStatus('closed')
      optionsRef.current.onClose?.()
      if (reconnectCountRef.current < maxReconnectAttempts) {
        // Exponential backoff: 3s, 6s, 12s, 24s, 48s (doubles each attempt, capped at 48s)
        const delay = Math.min(
          reconnectInterval * Math.pow(2, reconnectCountRef.current),
          48000,
        )
        reconnectCountRef.current++
        reconnectTimerRef.current = setTimeout(connect, delay)
      }
    }
  }, [url, reconnectInterval, maxReconnectAttempts, enabled])

  useEffect(() => {
    if (!enabled) return
    connect()
    return () => {
      clearTimeout(reconnectTimerRef.current)
      wsRef.current?.close()
    }
  }, [connect, enabled])

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data))
    }
  }, [])

  return { status, send }
}
