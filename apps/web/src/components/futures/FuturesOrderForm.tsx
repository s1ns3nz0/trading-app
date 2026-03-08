'use client'

import { useState } from 'react'
import { useTradingStore } from '@/stores/tradingStore'
import { useAuthStore } from '@/stores/authStore'
import { placeFuturesOrder } from '@/services/futuresTradingApi'
import { LeverageSelector } from './LeverageSelector'
import { cn } from '@/lib/utils'
import type { OrderType, PositionSide } from '@trading/types'

interface Props {
  symbol: string
}

const ORDER_TYPES: { value: OrderType; label: string }[] = [
  { value: 'limit', label: 'Limit' },
  { value: 'market', label: 'Market' },
  { value: 'stop_limit', label: 'Stop-Limit' },
]

export function FuturesOrderForm({ symbol }: Props) {
  const [positionSide, setPositionSide] = useState<PositionSide>('long')
  const [orderType, setOrderType] = useState<OrderType>('limit')
  const [price, setPrice] = useState('')
  const [quantity, setQuantity] = useState('')
  const [reduceOnly, setReduceOnly] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)

  const { isAuthenticated } = useAuthStore()
  const { ticker, leverage, marginMode, addOrder } = useTradingStore()

  const [baseAsset, quoteAsset] = symbol.split('-') as [string, string]

  const effectivePrice =
    orderType === 'market' ? ticker?.lastPrice ?? '0' : price

  // Estimate liquidation price
  const liqPrice = (() => {
    if (!effectivePrice || !quantity || !leverage) return null
    const entry = parseFloat(effectivePrice)
    const maintenanceMarginRate = 0.005
    if (positionSide === 'long') {
      return (entry * (1 - 1 / leverage + maintenanceMarginRate)).toFixed(2)
    } else {
      return (entry * (1 + 1 / leverage - maintenanceMarginRate)).toFixed(2)
    }
  })()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!isAuthenticated || !quantity) return
    setFeedback(null)
    setIsSubmitting(true)

    try {
      const order = await placeFuturesOrder({
        symbol,
        type: orderType,
        side: positionSide === 'long' ? 'buy' : 'sell',
        quantity,
        price: orderType !== 'market' ? price : undefined,
        leverage,
        marginMode,
        positionSide,
        reduceOnly,
        timeInForce: 'GTC',
      })
      addOrder(order)
      setQuantity('')
      setFeedback({ type: 'success', msg: `${positionSide === 'long' ? 'Long' : 'Short'} order placed` })
    } catch (err) {
      setFeedback({ type: 'error', msg: err instanceof Error ? err.message : 'Order failed' })
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="p-4 space-y-3">
      {/* Long / Short */}
      <div className="grid grid-cols-2 rounded overflow-hidden border border-border">
        <button
          onClick={() => setPositionSide('long')}
          className={cn(
            'py-2 text-sm font-semibold transition-colors',
            positionSide === 'long'
              ? 'bg-up text-white'
              : 'text-text-secondary hover:text-text-primary',
          )}
        >
          Long / Buy
        </button>
        <button
          onClick={() => setPositionSide('short')}
          className={cn(
            'py-2 text-sm font-semibold transition-colors',
            positionSide === 'short'
              ? 'bg-down text-white'
              : 'text-text-secondary hover:text-text-primary',
          )}
        >
          Short / Sell
        </button>
      </div>

      {/* Leverage + Margin mode row */}
      <div className="flex items-center gap-2">
        <LeverageSelector symbol={symbol} />
        <span className="text-text-muted text-xs">
          {marginMode === 'cross' ? 'Cross' : 'Isolated'}
        </span>
      </div>

      {/* Order type */}
      <div className="flex gap-1">
        {ORDER_TYPES.map(({ value, label }) => (
          <button
            key={value}
            onClick={() => setOrderType(value)}
            className={cn(
              'px-3 py-1 text-xs rounded transition-colors',
              orderType === value
                ? 'bg-bg-tertiary text-text-primary'
                : 'text-text-muted hover:text-text-secondary',
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <form onSubmit={handleSubmit} className="space-y-3">
        {orderType !== 'market' && (
          <div>
            <label className="block text-xs text-text-secondary mb-1">Price ({quoteAsset})</label>
            <div className="flex items-center bg-bg-tertiary border border-border rounded px-3">
              <input
                type="number"
                value={price}
                onChange={(e) => setPrice(e.target.value)}
                placeholder="0.00"
                className="flex-1 bg-transparent py-2 text-sm text-text-primary outline-none"
              />
              <span className="text-text-muted text-xs">{quoteAsset}</span>
            </div>
          </div>
        )}

        <div>
          <label className="block text-xs text-text-secondary mb-1">
            Contracts ({baseAsset})
          </label>
          <div className="flex items-center bg-bg-tertiary border border-border rounded px-3">
            <input
              type="number"
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              placeholder="0"
              className="flex-1 bg-transparent py-2 text-sm text-text-primary outline-none"
            />
            <span className="text-text-muted text-xs">{baseAsset}</span>
          </div>
        </div>

        {/* Estimated liquidation price */}
        {liqPrice && (
          <div className="flex justify-between text-xs">
            <span className="text-text-muted">Est. Liq. Price</span>
            <span className="text-down font-mono">{parseFloat(liqPrice).toLocaleString()} {quoteAsset}</span>
          </div>
        )}

        {/* Reduce-only */}
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={reduceOnly}
            onChange={(e) => setReduceOnly(e.target.checked)}
            className="accent-accent"
          />
          <span className="text-xs text-text-secondary">Reduce-Only</span>
        </label>

        {feedback && (
          <div
            className={cn(
              'px-3 py-2 rounded text-xs',
              feedback.type === 'success'
                ? 'bg-up/10 text-up border border-up/20'
                : 'bg-down/10 text-down border border-down/20',
            )}
          >
            {feedback.msg}
          </div>
        )}

        <button
          type="submit"
          disabled={!isAuthenticated || isSubmitting || !quantity}
          className={cn(
            'w-full py-2.5 rounded font-semibold text-white text-sm transition-opacity',
            'disabled:opacity-40 disabled:cursor-not-allowed',
            positionSide === 'long' ? 'bg-up hover:bg-up/90' : 'bg-down hover:bg-down/90',
          )}
        >
          {!isAuthenticated
            ? 'Login to Trade'
            : isSubmitting
              ? 'Placing…'
              : `Open ${positionSide === 'long' ? 'Long' : 'Short'}`}
        </button>
      </form>
    </div>
  )
}
