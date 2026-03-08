'use client'

import { useEffect, useState } from 'react'
import { getSupportedNetworks, getWithdrawalFee, submitWithdrawal } from '@/services/financeApi'
import { usePortfolioStore } from '@/stores/portfolioStore'
import type { Network } from '@trading/types'

const SUPPORTED_ASSETS = ['BTC', 'ETH', 'USDT', 'BNB', 'SOL']

export function WithdrawForm() {
  const [asset, setAsset] = useState('USDT')
  const [networks, setNetworks] = useState<Network[]>([])
  const [selectedNetwork, setSelectedNetwork] = useState('')
  const [address, setAddress] = useState('')
  const [tag, setTag] = useState('')
  const [amount, setAmount] = useState('')
  const [feeInfo, setFeeInfo] = useState<{ fee: string; minWithdrawal: string } | null>(null)
  const [status, setStatus] = useState<{ type: 'success' | 'error'; msg: string } | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  const { getAssetBalance } = usePortfolioStore()
  const balance = getAssetBalance(asset)?.free ?? '0'

  useEffect(() => {
    setSelectedNetwork('')
    setFeeInfo(null)
    getSupportedNetworks(asset).then((nets) => {
      setNetworks(nets)
      setSelectedNetwork(nets[0]?.id ?? '')
    })
  }, [asset])

  useEffect(() => {
    if (!selectedNetwork) return
    getWithdrawalFee(asset, selectedNetwork).then(setFeeInfo).catch(console.error)
  }, [asset, selectedNetwork])

  const receiveAmount =
    feeInfo && amount
      ? Math.max(0, parseFloat(amount) - parseFloat(feeInfo.fee)).toFixed(6)
      : '—'

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setStatus(null)
    setIsSubmitting(true)
    try {
      await submitWithdrawal({ asset, network: selectedNetwork, address, tag: tag || undefined, amount })
      setAddress('')
      setAmount('')
      setTag('')
      setStatus({ type: 'success', msg: 'Withdrawal submitted. Please check your email to confirm.' })
    } catch (err) {
      setStatus({ type: 'error', msg: err instanceof Error ? err.message : 'Withdrawal failed' })
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="max-w-lg space-y-6">
      {/* Asset */}
      <div>
        <label className="block text-sm text-text-secondary mb-2">Coin</label>
        <div className="flex flex-wrap gap-2">
          {SUPPORTED_ASSETS.map((a) => (
            <button
              key={a}
              onClick={() => setAsset(a)}
              className={`px-4 py-2 rounded-lg border text-sm font-medium transition-colors ${
                asset === a
                  ? 'border-accent text-accent bg-accent/10'
                  : 'border-border text-text-secondary hover:border-border-light'
              }`}
            >
              {a}
            </button>
          ))}
        </div>
      </div>

      {/* Network */}
      <div>
        <label className="block text-sm text-text-secondary mb-2">Network</label>
        <div className="flex flex-wrap gap-2">
          {networks.map((net) => (
            <button
              key={net.id}
              onClick={() => setSelectedNetwork(net.id)}
              className={`px-4 py-2 rounded-lg border text-sm transition-colors ${
                selectedNetwork === net.id
                  ? 'border-accent text-accent bg-accent/10'
                  : 'border-border text-text-secondary hover:border-border-light'
              }`}
            >
              {net.name}
            </button>
          ))}
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        {/* Address */}
        <div>
          <label className="block text-sm text-text-secondary mb-1">Withdrawal Address</label>
          <input
            type="text"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            placeholder="Enter recipient address"
            required
            className="w-full bg-bg-tertiary border border-border rounded-lg px-4 py-2.5 text-text-primary text-sm outline-none focus:border-accent transition-colors font-mono"
          />
        </div>

        {/* Tag (XRP, EOS, etc.) */}
        <div>
          <label className="block text-sm text-text-secondary mb-1">
            Memo / Tag <span className="text-text-muted">(if required)</span>
          </label>
          <input
            type="text"
            value={tag}
            onChange={(e) => setTag(e.target.value)}
            placeholder="Leave blank if not required"
            className="w-full bg-bg-tertiary border border-border rounded-lg px-4 py-2.5 text-text-primary text-sm outline-none focus:border-accent transition-colors font-mono"
          />
        </div>

        {/* Amount */}
        <div>
          <div className="flex justify-between text-xs text-text-muted mb-1">
            <label>Amount</label>
            <span>
              Available:{' '}
              <button
                type="button"
                onClick={() => setAmount(balance)}
                className="text-accent hover:underline"
              >
                {parseFloat(balance).toFixed(6)} {asset}
              </button>
            </span>
          </div>
          <div className="flex items-center bg-bg-tertiary border border-border rounded-lg px-4 focus-within:border-accent transition-colors">
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder={feeInfo?.minWithdrawal ?? '0'}
              min={feeInfo?.minWithdrawal ?? '0'}
              required
              className="flex-1 bg-transparent py-2.5 text-sm text-text-primary outline-none"
            />
            <span className="text-text-muted text-xs">{asset}</span>
          </div>
        </div>

        {/* Fee summary */}
        {feeInfo && (
          <div className="bg-bg-tertiary rounded-lg p-3 text-xs space-y-1.5">
            <div className="flex justify-between">
              <span className="text-text-muted">Network Fee</span>
              <span className="text-text-primary">{feeInfo.fee} {asset}</span>
            </div>
            <div className="flex justify-between border-t border-border pt-1.5">
              <span className="text-text-secondary font-medium">You Receive</span>
              <span className="text-text-primary font-medium">{receiveAmount} {asset}</span>
            </div>
          </div>
        )}

        {status && (
          <div
            className={`px-4 py-3 rounded text-sm ${
              status.type === 'success'
                ? 'bg-up/10 text-up border border-up/20'
                : 'bg-down/10 text-down border border-down/20'
            }`}
          >
            {status.msg}
          </div>
        )}

        <button
          type="submit"
          disabled={isSubmitting || !address || !amount}
          className="w-full py-2.5 bg-accent text-bg-primary font-semibold rounded-lg hover:bg-accent/90 transition-opacity disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isSubmitting ? 'Processing…' : `Withdraw ${asset}`}
        </button>
      </form>

      <div className="bg-down/5 border border-down/20 rounded-lg p-3 text-xs text-text-secondary">
        ⚠️ Double-check the address and network. Withdrawals cannot be reversed once submitted.
      </div>
    </div>
  )
}
