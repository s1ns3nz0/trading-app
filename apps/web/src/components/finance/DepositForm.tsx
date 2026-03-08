'use client'

import { useEffect, useState } from 'react'
import { getDepositAddress, getSupportedNetworks } from '@/services/financeApi'
import type { DepositAddress, Network } from '@trading/types'

const SUPPORTED_ASSETS = ['BTC', 'ETH', 'USDT', 'BNB', 'SOL']

export function DepositForm() {
  const [asset, setAsset] = useState('USDT')
  const [networks, setNetworks] = useState<Network[]>([])
  const [selectedNetwork, setSelectedNetwork] = useState('')
  const [address, setAddress] = useState<DepositAddress | null>(null)
  const [copied, setCopied] = useState(false)
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    setAddress(null)
    setSelectedNetwork('')
    getSupportedNetworks(asset).then((nets) => {
      setNetworks(nets)
      setSelectedNetwork(nets[0]?.id ?? '')
    })
  }, [asset])

  useEffect(() => {
    if (!selectedNetwork) return
    setIsLoading(true)
    setAddress(null)
    getDepositAddress(asset, selectedNetwork)
      .then(setAddress)
      .catch(console.error)
      .finally(() => setIsLoading(false))
  }, [asset, selectedNetwork])

  async function copyAddress() {
    if (!address?.address) return
    await navigator.clipboard.writeText(address.address)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const selectedNet = networks.find((n) => n.id === selectedNetwork)

  return (
    <div className="max-w-lg space-y-6">
      {/* Asset selection */}
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

      {/* Network selection */}
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

      {/* Network info */}
      {selectedNet && (
        <div className="grid grid-cols-2 gap-3 text-sm">
          <InfoRow label="Min. Deposit" value={`${selectedNet.minDeposit} ${asset}`} />
          <InfoRow label="Confirmations" value={String(selectedNet.confirmations)} />
          <InfoRow label="Est. Arrival" value={selectedNet.estimatedArrival} />
        </div>
      )}

      {/* Deposit address */}
      {isLoading ? (
        <div className="h-24 bg-bg-tertiary rounded-lg animate-pulse" />
      ) : address ? (
        <div className="bg-bg-tertiary border border-border rounded-lg p-4 space-y-3">
          <div className="text-xs text-text-muted">Deposit Address ({asset} — {selectedNet?.name})</div>
          <div className="flex items-center gap-2">
            <code className="flex-1 text-xs text-text-primary break-all font-mono bg-bg-secondary p-2 rounded">
              {address.address}
            </code>
            <button
              onClick={copyAddress}
              className="shrink-0 px-3 py-2 bg-accent text-bg-primary text-xs font-semibold rounded hover:bg-accent/90 transition-colors"
            >
              {copied ? 'Copied!' : 'Copy'}
            </button>
          </div>
          {address.tag && (
            <div>
              <div className="text-xs text-text-muted mb-1">Memo / Tag (required)</div>
              <code className="text-xs text-accent font-mono">{address.tag}</code>
            </div>
          )}
        </div>
      ) : null}

      {/* Warning */}
      <div className="bg-accent/5 border border-accent/20 rounded-lg p-3 text-xs text-text-secondary space-y-1">
        <p>⚠️ Only send <strong className="text-text-primary">{asset}</strong> on the <strong className="text-text-primary">{selectedNet?.name ?? '—'}</strong> network to this address.</p>
        <p>Sending other assets or using a different network will result in permanent loss.</p>
      </div>
    </div>
  )
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-text-muted">{label}</div>
      <div className="text-sm text-text-primary font-medium">{value}</div>
    </div>
  )
}
