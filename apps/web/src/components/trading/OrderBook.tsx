'use client'

import { useMemo } from 'react'
import { useOrderBook } from '@/hooks/useOrderBook'

interface Props {
  symbol: string
  maxLevels?: number
}

export function OrderBook({ symbol, maxLevels = 14 }: Props) {
  const { orderBook, isLoading } = useOrderBook(symbol)

  const maxTotal = useMemo(() => {
    if (!orderBook) return 1
    const askMax = parseFloat(orderBook.asks[orderBook.asks.length - 1]?.total ?? '1')
    const bidMax = parseFloat(orderBook.bids[orderBook.bids.length - 1]?.total ?? '1')
    return Math.max(askMax, bidMax)
  }, [orderBook])

  if (isLoading) {
    return (
      <div className="flex flex-col h-full animate-pulse gap-1 p-3">
        {Array.from({ length: 28 }).map((_, i) => (
          <div key={i} className="h-4 rounded bg-bg-tertiary" />
        ))}
      </div>
    )
  }

  const asks = (orderBook?.asks ?? []).slice(0, maxLevels).toReversed()
  const bids = (orderBook?.bids ?? []).slice(0, maxLevels)

  const spread =
    orderBook && orderBook.asks[0] && orderBook.bids[0]
      ? (parseFloat(orderBook.asks[0].price) - parseFloat(orderBook.bids[0].price)).toFixed(2)
      : '-'

  const spreadPercent =
    orderBook && orderBook.asks[0] && orderBook.bids[0]
      ? (
          ((parseFloat(orderBook.asks[0].price) - parseFloat(orderBook.bids[0].price)) /
            parseFloat(orderBook.bids[0].price)) *
          100
        ).toFixed(3)
      : '-'

  return (
    <div className="flex flex-col h-full font-mono text-xs select-none">
      {/* Column headers */}
      <div className="grid grid-cols-3 px-3 py-2 text-text-muted border-b border-border shrink-0">
        <span>Price</span>
        <span className="text-right">Size</span>
        <span className="text-right">Total</span>
      </div>

      {/* Asks — lowest at bottom */}
      <div className="flex flex-col-reverse overflow-hidden flex-1">
        {asks.map((level, i) => {
          const depth = (parseFloat(level.total) / maxTotal) * 100
          return (
            <div
              key={`ask-${i}`}
              className="relative grid grid-cols-3 px-3 py-[2px] hover:bg-bg-tertiary cursor-pointer"
            >
              <div
                className="absolute inset-y-0 right-0 bg-down/10"
                style={{ width: `${depth}%` }}
              />
              <span className="text-down z-10">{parseFloat(level.price).toLocaleString()}</span>
              <span className="text-right text-text-primary z-10">
                {parseFloat(level.size).toFixed(4)}
              </span>
              <span className="text-right text-text-secondary z-10">
                {parseFloat(level.total).toFixed(2)}
              </span>
            </div>
          )
        })}
      </div>

      {/* Spread */}
      <div className="px-3 py-1.5 border-y border-border shrink-0 flex items-center gap-3">
        <span className="text-text-primary font-medium text-sm">
          {orderBook?.bids[0]?.price
            ? parseFloat(orderBook.bids[0].price).toLocaleString()
            : '—'}
        </span>
        <span className="text-text-muted text-[10px]">
          Spread {spread} ({spreadPercent}%)
        </span>
      </div>

      {/* Bids */}
      <div className="overflow-hidden flex-1">
        {bids.map((level, i) => {
          const depth = (parseFloat(level.total) / maxTotal) * 100
          return (
            <div
              key={`bid-${i}`}
              className="relative grid grid-cols-3 px-3 py-[2px] hover:bg-bg-tertiary cursor-pointer"
            >
              <div
                className="absolute inset-y-0 right-0 bg-up/10"
                style={{ width: `${depth}%` }}
              />
              <span className="text-up z-10">{parseFloat(level.price).toLocaleString()}</span>
              <span className="text-right text-text-primary z-10">
                {parseFloat(level.size).toFixed(4)}
              </span>
              <span className="text-right text-text-secondary z-10">
                {parseFloat(level.total).toFixed(2)}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
