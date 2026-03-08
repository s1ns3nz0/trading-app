import { spotRequest } from './api'
import type { Order, PlaceOrderRequest, Portfolio, Ticker, OrderBook, Trade } from '@trading/types'

// ─── Market Data (unauthenticated) ───────────────────────────────────────────

export async function getTicker(symbol: string): Promise<Ticker> {
  return spotRequest<Ticker>(`/market/ticker/${symbol}`, { authenticated: false })
}

export async function getOrderBook(symbol: string, depth = 20): Promise<OrderBook> {
  return spotRequest<OrderBook>(`/market/orderbook/${symbol}?depth=${depth}`, {
    authenticated: false,
  })
}

export async function getRecentTrades(symbol: string, limit = 50): Promise<Trade[]> {
  return spotRequest<Trade[]>(`/market/trades/${symbol}?limit=${limit}`, {
    authenticated: false,
  })
}

export async function getSymbols(): Promise<string[]> {
  return spotRequest<string[]>('/market/symbols', { authenticated: false })
}

// ─── Trading (authenticated) ──────────────────────────────────────────────────

export async function placeSpotOrder(req: PlaceOrderRequest): Promise<Order> {
  return spotRequest<Order>('/orders', { method: 'POST', body: req })
}

export async function cancelSpotOrder(orderId: string): Promise<void> {
  return spotRequest<void>(`/orders/${orderId}`, { method: 'DELETE' })
}

export async function getOpenOrders(symbol?: string): Promise<Order[]> {
  const query = symbol ? `?symbol=${symbol}` : ''
  return spotRequest<Order[]>(`/orders/open${query}`)
}

export async function getOrderHistory(symbol?: string, limit = 50): Promise<Order[]> {
  const query = new URLSearchParams()
  if (symbol) query.set('symbol', symbol)
  query.set('limit', String(limit))
  return spotRequest<Order[]>(`/orders/history?${query}`)
}

// ─── Portfolio ────────────────────────────────────────────────────────────────

export async function getSpotPortfolio(): Promise<Portfolio> {
  return spotRequest<Portfolio>('/account/portfolio')
}
