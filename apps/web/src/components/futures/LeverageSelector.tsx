'use client'

import { useState } from 'react'
import { useTradingStore } from '@/stores/tradingStore'
import { setLeverage } from '@/services/futuresTradingApi'
import { cn } from '@/lib/utils'

const PRESETS = [1, 2, 3, 5, 10, 20, 25, 50, 75, 100, 125]

interface Props {
  symbol: string
}

export function LeverageSelector({ symbol }: Props) {
  const { leverage, setLeverage: storeLeverage } = useTradingStore()
  const [isOpen, setIsOpen] = useState(false)
  const [inputVal, setInputVal] = useState(String(leverage))

  async function applyLeverage(lev: number) {
    const clamped = Math.min(125, Math.max(1, lev))
    try {
      await setLeverage(symbol, clamped)
      storeLeverage(clamped)
      setInputVal(String(clamped))
      setIsOpen(false)
    } catch (err) {
      console.error('Failed to set leverage', err)
    }
  }

  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen((o) => !o)}
        className="flex items-center gap-1.5 px-3 py-1 bg-bg-tertiary border border-border rounded text-sm hover:border-border-light transition-colors"
      >
        <span className="text-accent font-semibold">{leverage}x</span>
        <span className="text-text-muted text-xs">Leverage</span>
      </button>

      {isOpen && (
        <div className="absolute top-full left-0 mt-1 z-50 bg-bg-secondary border border-border rounded-lg p-4 w-72 shadow-xl">
          <h3 className="text-sm font-semibold text-text-primary mb-3">Adjust Leverage</h3>

          {/* Slider */}
          <input
            type="range"
            min={1}
            max={125}
            value={leverage}
            onChange={(e) => {
              storeLeverage(Number(e.target.value))
              setInputVal(e.target.value)
            }}
            className="w-full accent-accent mb-3"
          />

          {/* Manual input */}
          <div className="flex items-center gap-2 mb-3">
            <div className="flex items-center bg-bg-tertiary border border-border rounded px-3 flex-1">
              <input
                type="number"
                value={inputVal}
                min={1}
                max={125}
                onChange={(e) => setInputVal(e.target.value)}
                className="bg-transparent py-1.5 text-sm text-text-primary outline-none w-full"
              />
              <span className="text-text-muted text-xs">x</span>
            </div>
            <button
              onClick={() => applyLeverage(Number(inputVal))}
              className="px-3 py-1.5 bg-accent text-bg-primary text-sm font-semibold rounded hover:bg-accent/90"
            >
              Set
            </button>
          </div>

          {/* Presets */}
          <div className="grid grid-cols-5 gap-1">
            {PRESETS.map((p) => (
              <button
                key={p}
                onClick={() => applyLeverage(p)}
                className={cn(
                  'py-1 text-xs rounded transition-colors',
                  leverage === p
                    ? 'bg-accent text-bg-primary font-semibold'
                    : 'bg-bg-tertiary text-text-secondary hover:bg-border',
                )}
              >
                {p}x
              </button>
            ))}
          </div>

          <p className="text-text-muted text-[10px] mt-3">
            Maximum position at {leverage}x leverage. Higher leverage = higher risk.
          </p>
        </div>
      )}
    </div>
  )
}
