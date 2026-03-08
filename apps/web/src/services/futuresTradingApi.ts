import { futuresRequest } from './api'
import type {
  Order,
  FuturesOrderRequest,
  FuturesPosition,
  FuturesAccountInfo,
  MarginMode,
} from '@trading/types'

// ─── Account ──────────────────────────────────────────────────────────────────

export async function getFuturesAccountInfo(): Promise<FuturesAccountInfo> {
  return futuresRequest<FuturesAccountInfo>('/account/info')
}

export async function setLeverage(symbol: string, leverage: number): Promise<void> {
  return futuresRequest<void>('/account/leverage', {
    method: 'POST',
    body: { symbol, leverage },
  })
}

export async function setMarginMode(symbol: string, marginMode: MarginMode): Promise<void> {
  return futuresRequest<void>('/account/margin-mode', {
    method: 'POST',
    body: { symbol, marginMode },
  })
}

// ─── Orders ───────────────────────────────────────────────────────────────────

export async function placeFuturesOrder(req: FuturesOrderRequest): Promise<Order> {
  return futuresRequest<Order>('/orders', { method: 'POST', body: req })
}

export async function cancelFuturesOrder(orderId: string): Promise<void> {
  return futuresRequest<void>(`/orders/${orderId}`, { method: 'DELETE' })
}

export async function getFuturesOpenOrders(symbol?: string): Promise<Order[]> {
  const query = symbol ? `?symbol=${symbol}` : ''
  return futuresRequest<Order[]>(`/orders/open${query}`)
}

// ─── Positions ────────────────────────────────────────────────────────────────

export async function getPositions(): Promise<FuturesPosition[]> {
  return futuresRequest<FuturesPosition[]>('/positions')
}

export async function closePosition(positionId: string, quantity?: string): Promise<Order> {
  return futuresRequest<Order>(`/positions/${positionId}/close`, {
    method: 'POST',
    body: quantity ? { quantity } : {},
  })
}

export async function addPositionMargin(positionId: string, amount: string): Promise<void> {
  return futuresRequest<void>(`/positions/${positionId}/margin`, {
    method: 'POST',
    body: { amount },
  })
}
