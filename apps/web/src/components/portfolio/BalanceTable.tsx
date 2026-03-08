'use client'

import { useEffect, useState } from 'react'
import { usePortfolioStore } from '@/stores/portfolioStore'
import { getSpotPortfolio } from '@/services/spotTradingApi'
import { cn, isPositive } from '@/lib/utils'

export function BalanceTable() {
  const { portfolio, setPortfolio, isLoading, setLoading } = usePortfolioStore()
  const [hideZero, setHideZero] = useState(false)

  useEffect(() => {
    setLoading(true)
    getSpotPortfolio().then(setPortfolio).catch(console.error)
  }, [setPortfolio, setLoading])

  const balances = (portfolio?.balances ?? []).filter(
    (b) => !hideZero || parseFloat(b.total) > 0,
  )

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="grid grid-cols-3 gap-4">
        <SummaryCard
          label="Total Balance"
          value={portfolio ? `${parseFloat(portfolio.totalValueUsdt).toLocaleString()} USDT` : '—'}
        />
        <SummaryCard
          label="Available"
          value={portfolio ? `${parseFloat(portfolio.availableUsdt).toLocaleString()} USDT` : '—'}
        />
        <SummaryCard
          label="24h PnL"
          value={portfolio ? `${portfolio.pnl24h} USDT (${portfolio.pnl24hPercent}%)` : '—'}
          highlight={portfolio ? (isPositive(portfolio.pnl24h) ? 'up' : 'down') : undefined}
        />
      </div>

      {/* Controls */}
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-text-primary">Asset Balances</h2>
        <label className="flex items-center gap-2 cursor-pointer text-xs text-text-secondary">
          <input
            type="checkbox"
            checked={hideZero}
            onChange={(e) => setHideZero(e.target.checked)}
            className="accent-accent"
          />
          Hide zero balances
        </label>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-text-muted text-xs">
              {['Asset', 'Total', 'Available', 'In Orders', 'USDT Value'].map((h) => (
                <th key={h} className="py-2 text-left font-normal">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {isLoading
              ? Array.from({ length: 5 }).map((_, i) => (
                  <tr key={i} className="border-b border-border/30">
                    {Array.from({ length: 5 }).map((__, j) => (
                      <td key={j} className="py-3 pr-4">
                        <div className="h-4 bg-bg-tertiary rounded animate-pulse" />
                      </td>
                    ))}
                  </tr>
                ))
              : balances.map((b) => (
                  <tr key={b.asset} className="border-b border-border/30 hover:bg-bg-tertiary/50">
                    <td className="py-3 pr-4 font-semibold text-text-primary">{b.asset}</td>
                    <td className="py-3 pr-4 font-mono text-text-primary">{parseFloat(b.total).toFixed(6)}</td>
                    <td className="py-3 pr-4 font-mono text-text-secondary">{parseFloat(b.free).toFixed(6)}</td>
                    <td className="py-3 pr-4 font-mono text-text-muted">{parseFloat(b.locked).toFixed(6)}</td>
                    <td className="py-3 font-mono text-text-primary">{parseFloat(b.usdtValue).toLocaleString()}</td>
                  </tr>
                ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function SummaryCard({
  label,
  value,
  highlight,
}: {
  label: string
  value: string
  highlight?: 'up' | 'down'
}) {
  return (
    <div className="bg-bg-secondary border border-border rounded-lg p-4">
      <div className="text-xs text-text-muted mb-1">{label}</div>
      <div
        className={cn(
          'text-lg font-semibold font-mono',
          highlight === 'up' ? 'text-up' : highlight === 'down' ? 'text-down' : 'text-text-primary',
        )}
      >
        {value}
      </div>
    </div>
  )
}
