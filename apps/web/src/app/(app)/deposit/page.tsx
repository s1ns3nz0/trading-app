'use client'

import { useState } from 'react'
import { useAuthStore } from '../../../stores/authStore'
import { useDeposit } from '../../../hooks/useDeposit'
import {
  createCryptoDeposit,
  createFiatDeposit,
  DepositResponse,
} from '../../../services/financeApi'

type Tab = 'CRYPTO' | 'FIAT'
type Asset = 'ETH' | 'BTC' | 'USDT'

const REQUIRED_CONFIRMATIONS: Record<Asset, number> = {
  ETH: 12,
  BTC: 6,
  USDT: 12,
}

function statusColor(status: string): string {
  if (status === 'CREDITED') return 'text-up'
  if (status === 'FAILED' || status === 'EXPIRED') return 'text-down'
  return 'text-text-secondary'
}

export default function DepositPage() {
  const { tokens } = useAuthStore()
  const accessToken = tokens?.access_token ?? ''

  const [tab, setTab] = useState<Tab>('CRYPTO')
  const [asset, setAsset] = useState<Asset>('ETH')
  const [amount, setAmount] = useState('')
  const [depositId, setDepositId] = useState<string | null>(null)
  const [createdDeposit, setCreatedDeposit] = useState<DepositResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const { deposit } = useDeposit(depositId, accessToken)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const result =
        tab === 'CRYPTO'
          ? await createCryptoDeposit(asset, amount, accessToken)
          : await createFiatDeposit(amount, accessToken)
      setCreatedDeposit(result)
      setDepositId(result.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Deposit failed')
    } finally {
      setLoading(false)
    }
  }

  const handleReset = () => {
    setCreatedDeposit(null)
    setDepositId(null)
    setAmount('')
    setError(null)
  }

  return (
    <div className="max-w-lg mx-auto p-6 space-y-6">
      <h1 className="text-2xl font-semibold text-text-primary">Deposit Funds</h1>

      {/* Tab selector */}
      <div className="flex gap-2 border-b border-border">
        {(['CRYPTO', 'FIAT'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              tab === t
                ? 'border-b-2 border-accent text-accent'
                : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            {t === 'CRYPTO' ? 'Crypto' : 'Bank Transfer'}
          </button>
        ))}
      </div>

      {!createdDeposit ? (
        <form onSubmit={handleSubmit} className="space-y-4">
          {tab === 'CRYPTO' && (
            <div>
              <label className="block text-sm text-text-secondary mb-1">
                Asset
              </label>
              <select
                value={asset}
                onChange={(e) => setAsset(e.target.value as Asset)}
                className="w-full bg-bg-secondary border border-border rounded-lg px-3 py-2 text-text-primary"
              >
                <option value="ETH">ETH (min 0.001)</option>
                <option value="BTC">BTC (min 0.0001)</option>
                <option value="USDT">USDT (min 10)</option>
              </select>
            </div>
          )}

          <div>
            <label className="block text-sm text-text-secondary mb-1">
              Amount{tab === 'FIAT' ? ' (USD, min $10)' : ''}
            </label>
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              step="any"
              min="0"
              required
              placeholder="0.00"
              className="w-full bg-bg-secondary border border-border rounded-lg px-3 py-2 text-text-primary"
            />
          </div>

          {error && (
            <p className="text-down text-sm">{error}</p>
          )}

          <button
            type="submit"
            disabled={loading || !amount}
            className="w-full bg-accent text-white py-2 rounded-lg font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {loading ? 'Creating…' : 'Create Deposit'}
          </button>
        </form>
      ) : (
        <div className="space-y-4">
          {/* Instructions */}
          {createdDeposit.type === 'CRYPTO' && (
            <div className="bg-bg-secondary border border-border rounded-xl p-4 space-y-2">
              <p className="text-sm text-text-secondary">
                Send {createdDeposit.asset} to this address:
              </p>
              <p className="font-mono text-sm text-text-primary break-all">
                {createdDeposit.walletAddress}
              </p>
              <p className="text-xs text-text-secondary">
                Amount: {createdDeposit.amount} {createdDeposit.asset}
              </p>
              <p className="text-xs text-text-secondary">
                Required confirmations: {REQUIRED_CONFIRMATIONS[asset]}
              </p>
            </div>
          )}

          {createdDeposit.type === 'FIAT' && (
            <div className="bg-bg-secondary border border-border rounded-xl p-4 space-y-2">
              <p className="text-sm text-text-secondary">Bank reference code:</p>
              <p className="font-mono text-lg font-semibold text-text-primary">
                {createdDeposit.bankReference}
              </p>
              <p className="text-xs text-text-secondary">
                Transfer ${createdDeposit.amount} USD using this reference
              </p>
            </div>
          )}

          {/* Live status */}
          {deposit && (
            <div className="flex items-center justify-between text-sm border border-border rounded-lg px-4 py-3">
              <span className="text-text-secondary">Status</span>
              <span className={`font-semibold ${statusColor(deposit.status)}`}>
                {deposit.status}
                {deposit.status === 'CONFIRMING' && deposit.confirmations > 0 && (
                  <span className="ml-1 font-normal text-text-secondary">
                    ({deposit.confirmations}/
                    {createdDeposit.type === 'CRYPTO'
                      ? REQUIRED_CONFIRMATIONS[asset]
                      : 1}{' '}
                    confirmations)
                  </span>
                )}
              </span>
            </div>
          )}

          <button
            onClick={handleReset}
            className="text-sm text-accent hover:underline"
          >
            Create another deposit
          </button>
        </div>
      )}
    </div>
  )
}
