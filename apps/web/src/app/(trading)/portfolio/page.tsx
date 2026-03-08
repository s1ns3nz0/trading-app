import type { Metadata } from 'next'
import { BalanceTable } from '@/components/portfolio/BalanceTable'
import { OpenOrders } from '@/components/portfolio/OpenOrders'

export const metadata: Metadata = { title: 'Portfolio' }

export default function PortfolioPage() {
  return (
    <div className="h-full overflow-y-auto p-6 space-y-8">
      <div>
        <h1 className="text-xl font-bold text-text-primary mb-6">Portfolio</h1>
        <BalanceTable />
      </div>

      <div>
        <h2 className="text-lg font-semibold text-text-primary mb-4">Open Orders</h2>
        <div className="bg-bg-secondary border border-border rounded-xl overflow-hidden">
          <OpenOrders symbol="" />
        </div>
      </div>
    </div>
  )
}
