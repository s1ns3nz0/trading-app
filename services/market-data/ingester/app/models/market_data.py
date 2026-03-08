"""
MarketData domain entities.
These are exchange-agnostic — all Binance-specific types are translated
by the ACL (BinanceTranslator) before reaching here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Interval(str, Enum):
    ONE_MINUTE      = "1m"
    FIVE_MINUTES    = "5m"
    FIFTEEN_MINUTES = "15m"
    ONE_HOUR        = "1h"
    FOUR_HOURS      = "4h"
    ONE_DAY         = "1d"


@dataclass(frozen=True)
class Symbol:
    """Normalized trading pair, e.g. 'BTC-USDT' (never 'BTCUSDT')."""
    value: str

    def __post_init__(self):
        if "-" not in self.value:
            raise ValueError(f"Symbol must be in 'BASE-QUOTE' format, got: {self.value!r}")

    def __str__(self) -> str:
        return self.value

    def to_binance(self) -> str:
        """BTC-USDT → BTCUSDT"""
        return self.value.replace("-", "")


@dataclass
class Ticker:
    """24-hour price statistics for a trading pair."""
    symbol: str
    last_price: str
    price_change: str
    price_change_percent: str
    volume: str
    quote_volume: str
    high: str
    low: str
    open_price: str
    open_time: int    # epoch ms
    close_time: int   # epoch ms
    timestamp: datetime = field(default_factory=_now_utc)

    def to_kafka_payload(self) -> dict:
        return {
            "symbol":             self.symbol,
            "lastPrice":          self.last_price,
            "priceChange":        self.price_change,
            "priceChangePercent": self.price_change_percent,
            "volume":             self.volume,
            "quoteVolume":        self.quote_volume,
            "high":               self.high,
            "low":                self.low,
            "openPrice":          self.open_price,
            "openTime":           self.open_time,
            "closeTime":          self.close_time,
            "timestamp":          self.timestamp.isoformat(),
        }

    def to_redis_hash(self) -> dict:
        return {
            "lastPrice":      self.last_price,
            "priceChange":    self.price_change,
            "priceChangePct": self.price_change_percent,
            "volume":         self.volume,
            "quoteVolume":    self.quote_volume,
            "high":           self.high,
            "low":            self.low,
            "openPrice":      self.open_price,
            "openTime":       str(self.open_time),
            "closeTime":      str(self.close_time),
        }


@dataclass(frozen=True)
class OrderBookLevel:
    """Single price level in an order book."""
    price: str
    quantity: str


@dataclass
class OrderBook:
    """Aggregated bid/ask depth for a symbol (top N levels)."""
    symbol: str
    bids: List[OrderBookLevel]   # sorted highest-price first
    asks: List[OrderBookLevel]   # sorted lowest-price first
    last_update_id: int
    timestamp: datetime = field(default_factory=_now_utc)

    def to_kafka_payload(self) -> dict:
        return {
            "symbol":       self.symbol,
            "bids":         [[b.price, b.quantity] for b in self.bids],
            "asks":         [[a.price, a.quantity] for a in self.asks],
            "lastUpdateId": self.last_update_id,
            "timestamp":    self.timestamp.isoformat(),
        }


@dataclass
class Trade:
    """Individual trade execution."""
    symbol: str
    trade_id: int
    price: str
    quantity: str
    buyer_maker: bool   # True if buyer was market maker (sell-initiated)
    trade_time: int     # ms
    timestamp: datetime = field(default_factory=_now_utc)

    def to_kafka_payload(self) -> dict:
        return {
            "symbol":     self.symbol,
            "tradeId":    self.trade_id,
            "price":      self.price,
            "qty":        self.quantity,
            "buyerMaker": self.buyer_maker,
            "tradeTime":  self.trade_time,
            "timestamp":  self.timestamp.isoformat(),
        }

    def to_redis_entry(self) -> str:
        import json
        return json.dumps({
            "id":         self.trade_id,
            "price":      self.price,
            "qty":        self.quantity,
            "buyerMaker": self.buyer_maker,
            "time":       self.trade_time,
        })


@dataclass
class Candle:
    """OHLCV bar for a symbol + interval."""
    symbol: str
    interval: str
    open_time: int    # epoch ms
    open: str
    high: str
    low: str
    close: str
    volume: str
    close_time: int   # epoch ms
    is_closed: bool   # True when bar is finalized

    def to_kafka_payload(self) -> dict:
        return {
            "symbol":    self.symbol,
            "interval":  self.interval,
            "openTime":  self.open_time,
            "open":      self.open,
            "high":      self.high,
            "low":       self.low,
            "close":     self.close,
            "volume":    self.volume,
            "closeTime": self.close_time,
            "isClosed":  self.is_closed,
        }
