'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { cn } from '@/lib/utils'

const SPOT_PAIRS = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'BNB-USDT']
const FUTURES_PAIRS = ['BTC-USDT', 'ETH-USDT', 'SOL-USDT']

const NAV_ITEMS = [
  { label: 'Spot', href: '/spot/BTC-USDT', icon: '◈' },
  { label: 'Futures', href: '/futures/BTC-USDT', icon: '◇' },
  { label: 'Portfolio', href: '/portfolio', icon: '▦' },
  { label: 'Deposit', href: '/deposit', icon: '↓' },
  { label: 'Withdraw', href: '/withdraw', icon: '↑' },
]

export function Sidebar() {
  const pathname = usePathname()

  return (
    <aside className="w-52 bg-bg-secondary border-r border-border flex flex-col shrink-0">
      {/* Logo */}
      <div className="px-4 py-4 border-b border-border">
        <span className="text-lg font-bold text-accent tracking-tight">CryptoTrade</span>
      </div>

      {/* Main nav */}
      <nav className="px-2 py-3 space-y-1 border-b border-border">
        {NAV_ITEMS.map(({ label, href, icon }) => (
          <Link
            key={href}
            href={href}
            className={cn(
              'flex items-center gap-2.5 px-3 py-2 rounded text-sm transition-colors',
              pathname.startsWith(href.split('/').slice(0, 2).join('/'))
                ? 'bg-bg-tertiary text-text-primary'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-tertiary/50',
            )}
          >
            <span className="text-text-muted w-4">{icon}</span>
            {label}
          </Link>
        ))}
      </nav>

      {/* Spot pairs */}
      <div className="px-2 py-3 border-b border-border">
        <div className="px-3 mb-1.5 text-[10px] uppercase tracking-wider text-text-muted">
          Spot Markets
        </div>
        {SPOT_PAIRS.map((pair) => (
          <Link
            key={pair}
            href={`/spot/${pair}`}
            className={cn(
              'flex items-center justify-between px-3 py-1.5 rounded text-xs transition-colors',
              pathname === `/spot/${pair}`
                ? 'bg-bg-tertiary text-text-primary'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-tertiary/50',
            )}
          >
            <span>{pair}</span>
          </Link>
        ))}
      </div>

      {/* Futures pairs */}
      <div className="px-2 py-3">
        <div className="px-3 mb-1.5 text-[10px] uppercase tracking-wider text-text-muted">
          Futures Markets
        </div>
        {FUTURES_PAIRS.map((pair) => (
          <Link
            key={pair}
            href={`/futures/${pair}`}
            className={cn(
              'flex items-center justify-between px-3 py-1.5 rounded text-xs transition-colors',
              pathname === `/futures/${pair}`
                ? 'bg-bg-tertiary text-text-primary'
                : 'text-text-secondary hover:text-text-primary hover:bg-bg-tertiary/50',
            )}
          >
            <span>{pair}</span>
            <span className="text-[9px] text-accent px-1 bg-accent/10 rounded">PERP</span>
          </Link>
        ))}
      </div>
    </aside>
  )
}
