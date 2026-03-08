import { create } from 'zustand'
import type { Portfolio } from '@trading/types'

interface PortfolioState {
  portfolio: Portfolio | null
  isLoading: boolean
  lastFetchedAt: number | null
  setPortfolio: (portfolio: Portfolio) => void
  setLoading: (isLoading: boolean) => void
  getAssetBalance: (asset: string) => { free: string; locked: string; total: string } | null
}

export const usePortfolioStore = create<PortfolioState>((set, get) => ({
  portfolio: null,
  isLoading: false,
  lastFetchedAt: null,

  setPortfolio: (portfolio) =>
    set({ portfolio, isLoading: false, lastFetchedAt: Date.now() }),

  setLoading: (isLoading) => set({ isLoading }),

  getAssetBalance: (asset) => {
    const balance = get().portfolio?.balances.find((b) => b.asset === asset)
    if (!balance) return null
    return { free: balance.free, locked: balance.locked, total: balance.total }
  },
}))
