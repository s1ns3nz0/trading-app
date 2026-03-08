'use client'

import { useEffect, useRef, useState } from 'react'
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type UTCTimestamp,
  ColorType,
  CrosshairMode,
} from 'lightweight-charts'
import { spotRequest } from '@/services/api'
import type { Candle } from '@trading/types'

interface Props {
  symbol: string
  height?: number
}

// Chart is initialized client-side only (no SSR)
export function PriceChart({ symbol, height = 400 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  // Initialize chart once — does not depend on symbol
  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#161a1e' },
        textColor: '#848e9c',
      },
      grid: {
        vertLines: { color: '#2b3139' },
        horzLines: { color: '#2b3139' },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: '#5e6673', labelBackgroundColor: '#1e2329' },
        horzLine: { color: '#5e6673', labelBackgroundColor: '#1e2329' },
      },
      rightPriceScale: {
        borderColor: '#2b3139',
      },
      timeScale: {
        borderColor: '#2b3139',
        timeVisible: true,
        secondsVisible: false,
      },
      height,
      width: containerRef.current.clientWidth,
    })

    const series = chart.addCandlestickSeries({
      upColor: '#02c076',
      downColor: '#f6465d',
      borderUpColor: '#02c076',
      borderDownColor: '#f6465d',
      wickUpColor: '#02c076',
      wickDownColor: '#f6465d',
    })

    chartRef.current = chart
    seriesRef.current = series

    // Resize observer
    const observer = new ResizeObserver(([entry]) => {
      if (entry) chart.applyOptions({ width: entry.contentRect.width })
    })
    observer.observe(containerRef.current)

    return () => {
      observer.disconnect()
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [height])

  // Fetch candle data whenever symbol changes
  useEffect(() => {
    if (!seriesRef.current) return

    let cancelled = false
    setIsLoading(true)

    spotRequest<Candle[]>(
      `/market/candles/${symbol}?interval=1m&limit=200`,
      { authenticated: false },
    )
      .then((candles) => {
        if (cancelled || !seriesRef.current) return

        const data: CandlestickData[] = candles.map((c) => ({
          time: Math.floor(c.openTime / 1000) as UTCTimestamp,
          open: parseFloat(c.open),
          high: parseFloat(c.high),
          low: parseFloat(c.low),
          close: parseFloat(c.close),
        }))

        seriesRef.current.setData(data)
        chartRef.current?.timeScale().fitContent()
      })
      .catch(console.error)
      .finally(() => {
        if (!cancelled) setIsLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [symbol])

  return (
    <div className="relative w-full bg-bg-secondary" style={{ height }}>
      {isLoading && (
        <div
          className="absolute inset-0 flex items-center justify-center text-sm text-text-secondary"
          style={{ zIndex: 1 }}
        >
          Loading chart...
        </div>
      )}
      <div ref={containerRef} className="w-full h-full" />
    </div>
  )
}
