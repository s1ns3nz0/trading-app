'use client'

import { useTicker } from '@/hooks/useTicker'
import { cn, formatPercent } from '@/lib/utils'

interface Props {
  symbol: string
}

export function MarketTicker({ symbol }: Props) {
  const { ticker } = useTicker(symbol)

  const isPositive = ticker ? parseFloat(ticker.priceChangePercent) >= 0 : true

  return (
    <div className="flex items-center gap-6 px-4 py-2 border-b border-border overflow-x-auto shrink-0">
      {/* Symbol */}
      <div className="shrink-0">
        <span className="text-lg font-bold text-text-primary">{symbol}</span>
      </div>

      {/* Last price */}
      <div className="shrink-0">
        <div className={cn('text-2xl font-bold font-mono', isPositive ? 'text-up' : 'text-down')}>
          {ticker ? parseFloat(ticker.lastPrice).toLocaleString() : '—'}
        </div>
      </div>

      {/* 24h change */}
      <TickerStat
        label="24h Change"
        value={
          ticker
            ? `${ticker.priceChange} (${formatPercent(ticker.priceChangePercent)})`
            : '—'
        }
        highlight={isPositive ? 'up' : 'down'}
      />

      <TickerStat label="24h High" value={ticker?.high24h ? parseFloat(ticker.high24h).toLocaleString() : '—'} />
      <TickerStat label="24h Low" value={ticker?.low24h ? parseFloat(ticker.low24h).toLocaleString() : '—'} />
      <TickerStat
        label="24h Volume"
        value={
          ticker
            ? `${parseFloat(ticker.volume24h).toLocaleString()} ${symbol.split('-')[0]}`
            : '—'
        }
      />
      <TickerStat
        label="24h Turnover"
        value={
          ticker
            ? `${parseFloat(ticker.quoteVolume24h).toLocaleString()} ${symbol.split('-')[1]}`
            : '—'
        }
      />
    </div>
  )
}

function TickerStat({
  label,
  value,
  highlight,
}: {
  label: string
  value: string
  highlight?: 'up' | 'down'
}) {
  return (
    <div className="shrink-0">
      <div className="text-[10px] text-text-muted mb-0.5">{label}</div>
      <div
        className={cn(
          'text-sm font-mono',
          highlight === 'up'
            ? 'text-up'
            : highlight === 'down'
              ? 'text-down'
              : 'text-text-primary',
        )}
      >
        {value}
      </div>
    </div>
  )
}
