import { MarketTicker } from '@/components/trading/MarketTicker'
import { PriceChart } from '@/components/trading/PriceChart'
import { OrderBook } from '@/components/trading/OrderBook'
import { TradeHistory } from '@/components/trading/TradeHistory'
import { FuturesOrderForm } from '@/components/futures/FuturesOrderForm'
import { PositionPanel } from '@/components/futures/PositionPanel'

interface Props {
  params: Promise<{ pair: string }>
}

export default async function FuturesTradingPage({ params }: Props) {
  const { pair } = await params
  const symbol = decodeURIComponent(pair)

  return (
    <div className="flex flex-col h-full">
      {/* Ticker */}
      <MarketTicker symbol={symbol} />

      {/* Main grid */}
      <div className="flex flex-1 min-h-0">
        {/* Chart + positions */}
        <div className="flex flex-col flex-1 min-w-0 border-r border-border">
          <div className="flex flex-1 min-h-0">
            {/* Chart */}
            <div className="flex-1 min-w-0">
              <PriceChart symbol={symbol} height={360} />
            </div>

            {/* Order book */}
            <div className="w-56 border-l border-border flex flex-col">
              <div className="px-3 py-2 border-b border-border shrink-0">
                <span className="text-xs font-medium text-text-secondary">Order Book</span>
              </div>
              <div className="flex-1 overflow-hidden">
                <OrderBook symbol={symbol} />
              </div>
            </div>
          </div>

          {/* Positions panel */}
          <div className="border-t border-border overflow-auto" style={{ maxHeight: '200px' }}>
            <div className="px-4 py-2 border-b border-border sticky top-0 bg-bg-primary">
              <span className="text-sm font-medium text-text-primary">Positions</span>
            </div>
            <PositionPanel />
          </div>
        </div>

        {/* Right: futures order form + trades */}
        <div className="w-64 flex flex-col shrink-0">
          <div className="border-b border-border overflow-y-auto">
            <FuturesOrderForm symbol={symbol} />
          </div>
          <div className="flex flex-col flex-1 min-h-0">
            <div className="px-3 py-2 border-b border-border shrink-0">
              <span className="text-xs font-medium text-text-secondary">Recent Trades</span>
            </div>
            <div className="flex-1 overflow-hidden">
              <TradeHistory symbol={symbol} />
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export function generateStaticParams() {
  return [
    { pair: 'BTC-USDT' },
    { pair: 'ETH-USDT' },
    { pair: 'SOL-USDT' },
  ]
}
