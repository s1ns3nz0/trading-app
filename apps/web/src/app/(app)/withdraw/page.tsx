'use client'

import { useState } from 'react'
import { useAuthStore } from '../../../stores/authStore'
import { useWithdrawal } from '../../../hooks/useWithdrawal'
import {
  createCryptoWithdrawal,
  createFiatWithdrawal,
  cancelWithdrawalById,
  WithdrawalResponse,
} from '../../../services/financeApi'

type Tab = 'CRYPTO' | 'FIAT'
type Asset = 'ETH' | 'BTC' | 'USDT'

function statusColor(status: string): string {
  if (status === 'EXECUTED') return 'text-up'
  if (status === 'REJECTED' || status === 'FAILED') return 'text-down'
  if (status === 'CANCELLED') return 'text-text-secondary'
  return 'text-accent'
}

export default function WithdrawPage() {
  const { tokens } = useAuthStore()
  const accessToken = tokens?.access_token ?? ''

  const [tab, setTab] = useState<Tab>('CRYPTO')
  const [asset, setAsset] = useState<Asset>('ETH')
  const [amount, setAmount] = useState('')
  const [toAddress, setToAddress] = useState('')
  const [bankAccount, setBankAccount] = useState('')
  const [bankRouting, setBankRouting] = useState('')
  const [withdrawalId, setWithdrawalId] = useState<string | null>(null)
  const [created, setCreated] = useState<WithdrawalResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const { withdrawal } = useWithdrawal(withdrawalId, accessToken)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const result = tab === 'CRYPTO'
        ? await createCryptoWithdrawal(asset, amount, toAddress, accessToken)
        : await createFiatWithdrawal(amount, bankAccount, bankRouting, accessToken)
      setCreated(result)
      setWithdrawalId(result.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Withdrawal failed')
    } finally {
      setLoading(false)
    }
  }

  const handleCancel = async () => {
    if (!withdrawalId) return
    try {
      await cancelWithdrawalById(withdrawalId, accessToken)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cannot cancel')
    }
  }

  return (
    <div className="max-w-lg mx-auto p-6 space-y-6">
      <h1 className="text-2xl font-semibold text-text-primary">Withdraw Funds</h1>

      <div className="flex gap-2 border-b border-border">
        {(['CRYPTO', 'FIAT'] as Tab[]).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              tab === t ? 'border-b-2 border-accent text-accent' : 'text-text-secondary hover:text-text-primary'
            }`}>
            {t === 'CRYPTO' ? 'Crypto' : 'Bank Transfer'}
          </button>
        ))}
      </div>

      {!created ? (
        <form onSubmit={handleSubmit} className="space-y-4">
          {tab === 'CRYPTO' && (
            <>
              <div>
                <label className="block text-sm text-text-secondary mb-1">Asset</label>
                <select value={asset} onChange={(e) => setAsset(e.target.value as Asset)}
                  className="w-full bg-bg-secondary border border-border rounded-lg px-3 py-2 text-text-primary">
                  <option value="ETH">ETH (max 10)</option>
                  <option value="BTC">BTC (max 1)</option>
                  <option value="USDT">USDT (max 50,000)</option>
                </select>
              </div>
              <div>
                <label className="block text-sm text-text-secondary mb-1">Destination Address</label>
                <input type="text" value={toAddress} onChange={(e) => setToAddress(e.target.value)}
                  required placeholder="0x... or bc1q..."
                  className="w-full bg-bg-secondary border border-border rounded-lg px-3 py-2 text-text-primary font-mono text-sm" />
              </div>
            </>
          )}

          {tab === 'FIAT' && (
            <>
              <div>
                <label className="block text-sm text-text-secondary mb-1">Bank Account Number</label>
                <input type="text" value={bankAccount} onChange={(e) => setBankAccount(e.target.value)}
                  required placeholder="Account number"
                  className="w-full bg-bg-secondary border border-border rounded-lg px-3 py-2 text-text-primary" />
              </div>
              <div>
                <label className="block text-sm text-text-secondary mb-1">Routing Number</label>
                <input type="text" value={bankRouting} onChange={(e) => setBankRouting(e.target.value)}
                  required placeholder="Routing / sort code"
                  className="w-full bg-bg-secondary border border-border rounded-lg px-3 py-2 text-text-primary" />
              </div>
            </>
          )}

          <div>
            <label className="block text-sm text-text-secondary mb-1">Amount</label>
            <input type="number" value={amount} onChange={(e) => setAmount(e.target.value)}
              step="any" min="0" required placeholder="0.00"
              className="w-full bg-bg-secondary border border-border rounded-lg px-3 py-2 text-text-primary" />
          </div>

          {error && <p className="text-down text-sm">{error}</p>}

          <button type="submit" disabled={loading || !amount}
            className="w-full bg-accent text-white py-2 rounded-lg font-medium hover:opacity-90 disabled:opacity-50 transition-opacity">
            {loading ? 'Submitting…' : 'Submit Withdrawal'}
          </button>
        </form>
      ) : (
        <div className="space-y-4">
          <div className="bg-bg-secondary border border-border rounded-xl p-4 space-y-2">
            <p className="text-sm text-text-secondary">Withdrawal ID</p>
            <p className="font-mono text-xs text-text-primary">{created.id}</p>
            {created.toAddress && (
              <>
                <p className="text-sm text-text-secondary mt-2">To Address</p>
                <p className="font-mono text-sm text-text-primary break-all">{created.toAddress}</p>
              </>
            )}
            <p className="text-sm text-text-secondary mt-2">
              Amount: {created.amount} {created.asset}
            </p>
          </div>

          {(withdrawal ?? created) && (
            <div className="flex items-center justify-between text-sm border border-border rounded-lg px-4 py-3">
              <span className="text-text-secondary">Status</span>
              <span className={`font-semibold ${statusColor((withdrawal ?? created)!.status)}`}>
                {(withdrawal ?? created)!.status}
              </span>
            </div>
          )}

          {withdrawal?.rejectionReason && (
            <p className="text-down text-sm">Reason: {withdrawal.rejectionReason}</p>
          )}

          {(withdrawal?.status ?? created?.status) === 'PENDING' && (
            <button onClick={handleCancel}
              className="text-sm text-down hover:underline">
              Cancel withdrawal
            </button>
          )}

          <button onClick={() => { setCreated(null); setWithdrawalId(null); setAmount('') }}
            className="text-sm text-accent hover:underline block">
            Submit another withdrawal
          </button>
        </div>
      )}
    </div>
  )
}
