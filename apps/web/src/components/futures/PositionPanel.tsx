'use client'

import { useEffect } from 'react'
import { useTradingStore } from '@/stores/tradingStore'
import { getPositions, closePosition } from '@/services/futuresTradingApi'
import { useAuthStore } from '@/stores/authStore'
import { cn } from '@/lib/utils'
import type { FuturesPosition } from '@trading/types'

export function PositionPanel() {
  const { positions, setPositions, cancelOrder } = useTradingStore()
  const { isAuthenticated } = useAuthStore()

  useEffect(() => {
    if (!isAuthenticated) return
    getPositions().then(setPositions).catch(console.error)
  }, [isAuthenticated, setPositions])

  if (!isAuthenticated) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted text-sm">
        Login to view positions
      </div>
    )
  }

  if (positions.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-text-muted text-sm">
        No open positions
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="border-b border-border text-text-muted">
            {[
              'Symbol', 'Size', 'Entry', 'Mark', 'Liq.', 'Margin',
              'Unrealized PnL', 'Leverage', 'Actions',
            ].map((h) => (
              <th key={h} className="px-3 py-2 text-left font-normal whitespace-nowrap">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => (
            <PositionRow key={pos.id} position={pos} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PositionRow({ position: pos }: { position: FuturesPosition }) {
  const { setPositions } = useTradingStore()
  const isLong = pos.side === 'long'
  const pnlPositive = parseFloat(pos.unrealizedPnl) >= 0

  async function handleClose() {
    try {
      await closePosition(pos.id)
      // Refresh positions
      getPositions().then(setPositions)
    } catch (err) {
      console.error('Close position failed', err)
    }
  }

  return (
    <tr className="border-b border-border/50 hover:bg-bg-tertiary">
      <td className="px-3 py-2 whitespace-nowrap">
        <span className="text-text-primary">{pos.symbol}</span>
        <span
          className={cn(
            'ml-2 text-[10px] px-1.5 py-0.5 rounded',
            isLong ? 'bg-up/20 text-up' : 'bg-down/20 text-down',
          )}
        >
          {isLong ? 'Long' : 'Short'}
        </span>
      </td>
      <td className="px-3 py-2 text-text-primary">{pos.size}</td>
      <td className="px-3 py-2 text-text-primary">{parseFloat(pos.entryPrice).toLocaleString()}</td>
      <td className="px-3 py-2 text-text-primary">{parseFloat(pos.markPrice).toLocaleString()}</td>
      <td className="px-3 py-2 text-down">{parseFloat(pos.liquidationPrice).toLocaleString()}</td>
      <td className="px-3 py-2 text-text-primary">{pos.margin}</td>
      <td className={cn('px-3 py-2 font-medium', pnlPositive ? 'text-up' : 'text-down')}>
        {pnlPositive ? '+' : ''}
        {pos.unrealizedPnl}
        <span className="text-text-muted ml-1 font-normal">USDT</span>
      </td>
      <td className="px-3 py-2">
        <span className="text-accent">{pos.leverage}x</span>
        <span className="text-text-muted ml-1">
          {pos.marginMode === 'cross' ? 'Cross' : 'Iso'}
        </span>
      </td>
      <td className="px-3 py-2">
        <button
          onClick={handleClose}
          className="px-2 py-1 text-[10px] border border-down/50 text-down rounded hover:bg-down/10 transition-colors"
        >
          Close
        </button>
      </td>
    </tr>
  )
}
