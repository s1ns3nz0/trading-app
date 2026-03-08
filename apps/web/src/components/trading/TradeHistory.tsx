'use client'

import { useCallback, useState } from 'react'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useTradingStore } from '@/stores/tradingStore'
import { cn, formatDate } from '@/lib/utils'
import type { WsTradeMessage } from '@trading/types'

interface Props {
  symbol: string
}

export function TradeHistory({ symbol }: Props) {
  const { recentTrades, addTrade } = useTradingStore()
  const [, setConnected] = useState(false)

  const wsUrl = `${process.env.NEXT_PUBLIC_WS_URL}/market/trades/${symbol.toLowerCase()}`

  const handleMessage = useCallback(
    (data: unknown) => {
      const msg = data as WsTradeMessage
      if (msg.type === 'trade') addTrade(msg.data)
    },
    [addTrade],
  )

  useWebSocket(wsUrl, {
    onMessage: handleMessage,
    onOpen: () => setConnected(true),
    onClose: () => setConnected(false),
  })

  return (
    <div className="flex flex-col h-full font-mono text-xs">
      <div className="grid grid-cols-3 px-3 py-2 text-text-muted border-b border-border shrink-0">
        <span>Price</span>
        <span className="text-right">Size</span>
        <span className="text-right">Time</span>
      </div>

      <div className="overflow-y-auto flex-1">
        {recentTrades.length === 0 && (
          <div className="flex items-center justify-center h-20 text-text-muted">
            Waiting for trades…
          </div>
        )}
        {recentTrades.map((trade) => (
          <div
            key={trade.id}
            className="grid grid-cols-3 px-3 py-[2px] hover:bg-bg-tertiary"
          >
            <span className={trade.side === 'buy' ? 'text-up' : 'text-down'}>
              {parseFloat(trade.price).toLocaleString()}
            </span>
            <span className="text-right text-text-primary">
              {parseFloat(trade.size).toFixed(4)}
            </span>
            <span className="text-right text-text-muted">
              {new Date(trade.timestamp).toLocaleTimeString('en-US', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                hour12: false,
              })}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
