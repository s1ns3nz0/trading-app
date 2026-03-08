'use client'

import { useState } from 'react'
import { useAuthStore } from '@/stores/authStore'
import { usePortfolioStore } from '@/stores/portfolioStore'
import { useTradingStore } from '@/stores/tradingStore'
import { placeSpotOrder } from '@/services/spotTradingApi'
import { cn } from '@/lib/utils'
import type { OrderType, Side } from '@trading/types'

interface Props {
  symbol: string
}

const ORDER_TYPES: { value: OrderType; label: string }[] = [
  { value: 'limit', label: 'Limit' },
  { value: 'market', label: 'Market' },
  { value: 'stop_limit', label: 'Stop-Limit' },
]

const PRESETS = [25, 50, 75, 100]

export function OrderForm({ symbol }: Props) {
  const [side, setSide] = useState<Side>('buy')
  const [orderType, setOrderType] = useState<OrderType>('limit')
  const [price, setPrice] = useState('')
  const [stopPrice, setStopPrice] = useState('')
  const [quantity, setQuantity] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)

  const { isAuthenticated } = useAuthStore()
  const { getAssetBalance } = usePortfolioStore()
  const { ticker, addOrder } = useTradingStore()

  const [baseAsset, quoteAsset] = symbol.split('-') as [string, string]
  const availableBalance =
    side === 'buy'
      ? getAssetBalance(quoteAsset)?.free ?? '0'
      : getAssetBalance(baseAsset)?.free ?? '0'

  const effectivePrice =
    orderType === 'market' ? ticker?.lastPrice ?? '0' : price

  const total =
    effectivePrice && quantity
      ? (parseFloat(effectivePrice) * parseFloat(quantity)).toFixed(2)
      : '0.00'

  function applyPreset(pct: number) {
    const available = parseFloat(availableBalance)
    if (!available) return
    if (side === 'buy' && parseFloat(effectivePrice) > 0) {
      setQuantity(((available * pct) / 100 / parseFloat(effectivePrice)).toFixed(6))
    } else if (side === 'sell') {
      setQuantity(((available * pct) / 100).toFixed(6))
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!isAuthenticated || !quantity) return
    setFeedback(null)
    setIsSubmitting(true)

    try {
      const order = await placeSpotOrder({
        symbol,
        type: orderType,
        side,
        quantity,
        price: orderType !== 'market' ? price : undefined,
        stopPrice: orderType === 'stop_limit' ? stopPrice : undefined,
        timeInForce: 'GTC',
      })
      addOrder(order)
      setQuantity('')
      setFeedback({ type: 'success', msg: `${side === 'buy' ? 'Buy' : 'Sell'} order placed` })
    } catch (err) {
      setFeedback({ type: 'error', msg: err instanceof Error ? err.message : 'Order failed' })
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="p-4 space-y-3">
      {/* Buy / Sell toggle */}
      <div className="grid grid-cols-2 rounded overflow-hidden border border-border">
        <button
          onClick={() => setSide('buy')}
          className={cn(
            'py-2 text-sm font-semibold transition-colors',
            side === 'buy' ? 'bg-up text-white' : 'text-text-secondary hover:text-text-primary',
          )}
        >
          Buy {baseAsset}
        </button>
        <button
          onClick={() => setSide('sell')}
          className={cn(
            'py-2 text-sm font-semibold transition-colors',
            side === 'sell' ? 'bg-down text-white' : 'text-text-secondary hover:text-text-primary',
          )}
        >
          Sell {baseAsset}
        </button>
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
        {/* Available balance */}
        <div className="flex justify-between text-xs text-text-muted">
          <span>Available</span>
          <span className="text-text-secondary">
            {parseFloat(availableBalance).toFixed(4)}{' '}
            {side === 'buy' ? quoteAsset : baseAsset}
          </span>
        </div>

        {/* Stop price (stop-limit only) */}
        {orderType === 'stop_limit' && (
          <div>
            <label className="block text-xs text-text-secondary mb-1">Stop ({quoteAsset})</label>
            <InputField value={stopPrice} onChange={setStopPrice} unit={quoteAsset} step="0.01" />
          </div>
        )}

        {/* Limit price */}
        {orderType !== 'market' && (
          <div>
            <label className="block text-xs text-text-secondary mb-1">Price ({quoteAsset})</label>
            <InputField value={price} onChange={setPrice} unit={quoteAsset} step="0.01" />
          </div>
        )}

        {/* Market price indicator */}
        {orderType === 'market' && (
          <div className="bg-bg-tertiary rounded px-3 py-2 flex justify-between text-xs">
            <span className="text-text-muted">Market Price</span>
            <span className="text-text-primary">
              {ticker ? parseFloat(ticker.lastPrice).toLocaleString() : '—'} {quoteAsset}
            </span>
          </div>
        )}

        {/* Quantity */}
        <div>
          <label className="block text-xs text-text-secondary mb-1">Amount ({baseAsset})</label>
          <InputField value={quantity} onChange={setQuantity} unit={baseAsset} step="0.0001" />
        </div>

        {/* Presets */}
        <div className="grid grid-cols-4 gap-1">
          {PRESETS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => applyPreset(p)}
              className="py-1 text-xs text-text-muted bg-bg-tertiary hover:bg-border rounded transition-colors"
            >
              {p}%
            </button>
          ))}
        </div>

        {/* Total */}
        <div className="flex justify-between text-xs text-text-muted">
          <span>Total</span>
          <span className="text-text-primary">
            {total} {quoteAsset}
          </span>
        </div>

        {/* Feedback */}
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

        {/* Submit */}
        <button
          type="submit"
          disabled={!isAuthenticated || isSubmitting || !quantity}
          className={cn(
            'w-full py-2.5 rounded font-semibold text-white text-sm transition-opacity',
            'disabled:opacity-40 disabled:cursor-not-allowed',
            side === 'buy' ? 'bg-up hover:bg-up/90' : 'bg-down hover:bg-down/90',
          )}
        >
          {!isAuthenticated
            ? 'Login to Trade'
            : isSubmitting
              ? 'Placing…'
              : `${side === 'buy' ? 'Buy' : 'Sell'} ${baseAsset}`}
        </button>
      </form>
    </div>
  )
}

function InputField({
  value,
  onChange,
  unit,
  step,
}: {
  value: string
  onChange: (v: string) => void
  unit: string
  step?: string
}) {
  return (
    <div className="flex items-center bg-bg-tertiary border border-border rounded px-3 focus-within:border-border-light transition-colors">
      <input
        type="number"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="0"
        step={step}
        min="0"
        className="flex-1 bg-transparent py-2 text-sm text-text-primary outline-none"
      />
      <span className="text-text-muted text-xs shrink-0">{unit}</span>
    </div>
  )
}
