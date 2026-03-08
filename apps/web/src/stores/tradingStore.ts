import { create } from 'zustand'
import type { Order, FuturesPosition, OrderBook, Ticker, Trade, MarginMode } from '@trading/types'

interface TradingState {
  // Market
  selectedPair: string
  ticker: Ticker | null
  orderBook: OrderBook | null
  recentTrades: Trade[]

  // User orders & positions
  openOrders: Order[]
  orderHistory: Order[]
  positions: FuturesPosition[]

  // Futures settings
  leverage: number
  marginMode: MarginMode

  // Actions
  setSelectedPair: (pair: string) => void
  setTicker: (ticker: Ticker) => void
  updateOrderBook: (orderBook: OrderBook) => void
  addTrade: (trade: Trade) => void
  setOpenOrders: (orders: Order[]) => void
  addOrder: (order: Order) => void
  updateOrder: (order: Order) => void
  cancelOrder: (orderId: string) => void
  setPositions: (positions: FuturesPosition[]) => void
  updatePosition: (position: FuturesPosition) => void
  setLeverage: (leverage: number) => void
  setMarginMode: (mode: MarginMode) => void
}

export const useTradingStore = create<TradingState>((set) => ({
  selectedPair: 'BTC-USDT',
  ticker: null,
  orderBook: null,
  recentTrades: [],
  openOrders: [],
  orderHistory: [],
  positions: [],
  leverage: 10,
  marginMode: 'cross',

  setSelectedPair: (pair) => set({ selectedPair: pair }),

  setTicker: (ticker) => set({ ticker }),

  updateOrderBook: (orderBook) => set({ orderBook }),

  addTrade: (trade) =>
    set((state) => ({
      recentTrades: [trade, ...state.recentTrades].slice(0, 50),
    })),

  setOpenOrders: (orders) => set({ openOrders: orders }),

  addOrder: (order) =>
    set((state) => ({ openOrders: [order, ...state.openOrders] })),

  updateOrder: (updated) =>
    set((state) => {
      const isOpen = updated.status === 'open' || updated.status === 'partial'
      if (isOpen) {
        return {
          openOrders: state.openOrders.map((o) => (o.id === updated.id ? updated : o)),
        }
      }
      // Move to history if filled/cancelled
      return {
        openOrders: state.openOrders.filter((o) => o.id !== updated.id),
        orderHistory: [updated, ...state.orderHistory].slice(0, 200),
      }
    }),

  cancelOrder: (orderId) =>
    set((state) => ({
      openOrders: state.openOrders.filter((o) => o.id !== orderId),
    })),

  setPositions: (positions) => set({ positions }),

  updatePosition: (updated) =>
    set((state) => ({
      positions: state.positions.map((p) => (p.id === updated.id ? updated : p)),
    })),

  setLeverage: (leverage) => set({ leverage }),
  setMarginMode: (marginMode) => set({ marginMode }),
}))
