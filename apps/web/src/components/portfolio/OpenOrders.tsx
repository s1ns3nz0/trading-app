'use client'

import { useOrders } from '@/hooks/useOrders'
import { cancelSpotOrder } from '@/services/spotTradingApi'
import { useTradingStore } from '@/stores/tradingStore'
import { cn, formatDate } from '@/lib/utils'

interface Props {
  symbol: string
}

export function OpenOrders({ symbol }: Props) {
  const { openOrders } = useOrders(symbol)
  const { cancelOrder } = useTradingStore()

  async function handleCancel(orderId: string) {
    try {
      await cancelSpotOrder(orderId)
      cancelOrder(orderId)
    } catch (err) {
      console.error('Cancel failed', err)
    }
  }

  if (openOrders.length === 0) {
    return (
      <div className="flex items-center justify-center py-8 text-text-muted text-sm">
        No open orders
      </div>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs font-mono">
        <thead>
          <tr className="border-b border-border text-text-muted">
            {['Date', 'Pair', 'Type', 'Side', 'Price', 'Amount', 'Filled', 'Status', ''].map(
              (h) => (
                <th key={h} className="px-3 py-2 text-left font-normal whitespace-nowrap">
                  {h}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {openOrders.map((order) => (
            <tr key={order.id} className="border-b border-border/30 hover:bg-bg-tertiary">
              <td className="px-3 py-2 text-text-muted whitespace-nowrap">
                {formatDate(order.createdAt)}
              </td>
              <td className="px-3 py-2 text-text-primary">{order.symbol}</td>
              <td className="px-3 py-2 text-text-secondary capitalize">{order.type.replace('_', '-')}</td>
              <td
                className={cn(
                  'px-3 py-2 capitalize font-semibold',
                  order.side === 'buy' ? 'text-up' : 'text-down',
                )}
              >
                {order.side}
              </td>
              <td className="px-3 py-2 text-text-primary">
                {order.price ? parseFloat(order.price).toLocaleString() : 'Market'}
              </td>
              <td className="px-3 py-2 text-text-primary">{order.quantity}</td>
              <td className="px-3 py-2 text-text-secondary">
                {order.filledQuantity} / {order.quantity}
              </td>
              <td className="px-3 py-2">
                <span
                  className={cn(
                    'px-1.5 py-0.5 rounded text-[10px]',
                    order.status === 'open' && 'bg-accent/20 text-accent',
                    order.status === 'partial' && 'bg-up/20 text-up',
                  )}
                >
                  {order.status}
                </span>
              </td>
              <td className="px-3 py-2">
                <button
                  onClick={() => handleCancel(order.id)}
                  className="text-down hover:underline"
                >
                  Cancel
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
