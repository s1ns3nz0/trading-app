import type { Metadata } from 'next'
import { DepositForm } from '@/components/finance/DepositForm'

export const metadata: Metadata = { title: 'Deposit' }

export default function DepositPage() {
  return (
    <div className="h-full overflow-y-auto p-6">
      <h1 className="text-xl font-bold text-text-primary mb-6">Deposit</h1>
      <DepositForm />
    </div>
  )
}
