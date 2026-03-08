import type { Metadata } from 'next'
import { WithdrawForm } from '@/components/finance/WithdrawForm'

export const metadata: Metadata = { title: 'Withdraw' }

export default function WithdrawPage() {
  return (
    <div className="h-full overflow-y-auto p-6">
      <h1 className="text-xl font-bold text-text-primary mb-6">Withdraw</h1>
      <WithdrawForm />
    </div>
  )
}
