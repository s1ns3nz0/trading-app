import { financeRequest } from './api'
import type {
  DepositAddress,
  DepositRecord,
  WithdrawalRequest,
  WithdrawalRecord,
  Network,
} from '@trading/types'

const FINANCE_API = process.env.NEXT_PUBLIC_FINANCE_API_URL ?? ''

// ─── Deposit (new deposit-service endpoints) ──────────────────────────────────

export interface DepositResponse {
  id: string
  type: 'CRYPTO' | 'FIAT'
  asset: string
  amount: string
  status: 'PENDING' | 'CONFIRMING' | 'CONFIRMED' | 'CREDITED' | 'FAILED' | 'EXPIRED'
  walletAddress?: string
  bankReference?: string
  txHash?: string
  confirmations: number
  expiresAt: string
  creditedAt?: string
  createdAt: string
}

export async function createCryptoDeposit(
  asset: string,
  amount: string,
  token: string,
): Promise<DepositResponse> {
  const res = await fetch(`${FINANCE_API}/deposits/crypto`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ asset, amount }),
  })
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.detail ?? 'Failed to create deposit')
  }
  return res.json()
}

export async function createFiatDeposit(
  amount: string,
  token: string,
): Promise<DepositResponse> {
  const res = await fetch(`${FINANCE_API}/deposits/fiat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ amount }),
  })
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.detail ?? 'Failed to create fiat deposit')
  }
  return res.json()
}

export async function getDeposit(
  depositId: string,
  token: string,
): Promise<DepositResponse> {
  const res = await fetch(`${FINANCE_API}/deposits/${depositId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Deposit not found')
  return res.json()
}

export async function listDeposits(token: string): Promise<DepositResponse[]> {
  const res = await fetch(`${FINANCE_API}/deposits`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to fetch deposits')
  return res.json()
}

// ─── Deposit (legacy network/address endpoints) ────────────────────────────────

export async function getSupportedNetworks(asset: string): Promise<Network[]> {
  return financeRequest<Network[]>(`/deposit/networks/${asset}`)
}

export async function getDepositAddress(asset: string, network: string): Promise<DepositAddress> {
  return financeRequest<DepositAddress>(`/deposit/address?asset=${asset}&network=${network}`)
}

export async function getDepositHistory(limit = 20): Promise<DepositRecord[]> {
  return financeRequest<DepositRecord[]>(`/deposit/history?limit=${limit}`)
}

// ─── Withdrawal (new withdrawal-service endpoints) ────────────────────────────

export interface WithdrawalResponse {
  id: string
  type: 'CRYPTO' | 'FIAT'
  asset: string
  amount: string
  status: 'PENDING' | 'PROCESSING' | 'EXECUTED' | 'REJECTED' | 'FAILED' | 'CANCELLED'
  toAddress?: string
  txHash?: string
  bankAccountNumber?: string
  rejectionReason?: string
  reservedAt?: string
  executedAt?: string
  expiresAt: string
  createdAt: string
}

export async function createCryptoWithdrawal(
  asset: string,
  amount: string,
  toAddress: string,
  token: string,
): Promise<WithdrawalResponse> {
  const res = await fetch(`${FINANCE_API}/withdrawals/crypto`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ asset, amount, to_address: toAddress }),
  })
  if (!res.ok) { const err = await res.json(); throw new Error(err.detail ?? 'Failed') }
  return res.json()
}

export async function createFiatWithdrawal(
  amount: string,
  bankAccountNumber: string,
  bankRoutingNumber: string,
  token: string,
): Promise<WithdrawalResponse> {
  const res = await fetch(`${FINANCE_API}/withdrawals/fiat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ amount, bank_account_number: bankAccountNumber, bank_routing_number: bankRoutingNumber }),
  })
  if (!res.ok) { const err = await res.json(); throw new Error(err.detail ?? 'Failed') }
  return res.json()
}

export async function getWithdrawalById(id: string, token: string): Promise<WithdrawalResponse> {
  const res = await fetch(`${FINANCE_API}/withdrawals/${id}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Withdrawal not found')
  return res.json()
}

export async function cancelWithdrawalById(id: string, token: string): Promise<void> {
  const res = await fetch(`${FINANCE_API}/withdrawals/${id}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok && res.status !== 204) {
    const err = await res.json()
    throw new Error(err.detail ?? 'Cannot cancel')
  }
}

// ─── Withdrawal (legacy endpoints) ────────────────────────────────────────────

export async function submitWithdrawal(req: WithdrawalRequest): Promise<WithdrawalRecord> {
  return financeRequest<WithdrawalRecord>('/withdrawal', { method: 'POST', body: req })
}

export async function getWithdrawalHistory(limit = 20): Promise<WithdrawalRecord[]> {
  return financeRequest<WithdrawalRecord[]>(`/withdrawal/history?limit=${limit}`)
}

export async function cancelWithdrawal(withdrawalId: string): Promise<void> {
  return financeRequest<void>(`/withdrawal/${withdrawalId}/cancel`, { method: 'POST' })
}

export async function getWithdrawalFee(
  asset: string,
  network: string,
): Promise<{ fee: string; minWithdrawal: string }> {
  return financeRequest(`/withdrawal/fee?asset=${asset}&network=${network}`)
}
