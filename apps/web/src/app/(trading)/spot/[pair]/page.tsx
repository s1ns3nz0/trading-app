import { MarketTicker } from '@/components/trading/MarketTicker'
import { PriceChart } from '@/components/trading/PriceChart'
import { OrderBook } from '@/components/trading/OrderBook'
import { OrderForm } from '@/components/trading/OrderForm'
import { TradeHistory } from '@/components/trading/TradeHistory'
import { OpenOrders } from '@/components/portfolio/OpenOrders'

interface Props {
  params: Promise<{ pair: string }>
}

export default async function SpotTradingPage({ params }: Props) {
  const { pair } = await params
  const symbol = decodeURIComponent(pair)

  return (
    <div className="flex flex-col h-full">
      {/* Ticker bar */}
      <MarketTicker symbol={symbol} />

      {/* Main trading grid */}
      <div className="flex flex-1 min-h-0">
        {/* Chart + Order book */}
        <div className="flex flex-1 min-w-0 border-r border-border">
          {/* Price chart — takes remaining space */}
          <div className="flex flex-col flex-1 min-w-0">
            <PriceChart symbol={symbol} height={400} />

            {/* Bottom panel: open orders */}
            <div className="border-t border-border flex-1 overflow-auto">
              <div className="px-4 py-2 border-b border-border">
                <span className="text-sm font-medium text-text-primary">Open Orders</span>
              </div>
              <OpenOrders symbol={symbol} />
            </div>
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

        {/* Right panel: order form + trade history */}
        <div className="w-64 flex flex-col shrink-0">
          {/* Order form */}
          <div className="border-b border-border overflow-y-auto">
            <OrderForm symbol={symbol} />
          </div>

          {/* Recent trades */}
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
    { pair: 'BNB-USDT' },
  ]
}
