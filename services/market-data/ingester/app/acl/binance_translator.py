"""
Anti-Corruption Layer: translates Binance wire format → domain model.
No Binance types leak beyond this boundary.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..models.market_data import Ticker, OrderBook, OrderBookLevel, Trade, Candle

# Binance uses concatenated symbols (BTCUSDT). We normalize to BASE-QUOTE.
_QUOTE_SUFFIXES = ("USDT", "BUSD", "USDC", "BTC", "ETH", "BNB")


def _normalize_symbol(binance_symbol: str) -> str:
    """Convert 'BTCUSDT' → 'BTC-USDT'."""
    s = binance_symbol.upper()
    for quote in _QUOTE_SUFFIXES:
        if s.endswith(quote) and len(s) > len(quote):
            base = s[: -len(quote)]
            return f"{base}-{quote}"
    return s  # fallback: return as-is


def _ms_to_datetime(epoch_ms: int) -> datetime:
    """Convert Unix milliseconds to UTC datetime."""
    return datetime.fromtimestamp(epoch_ms / 1000.0, tz=timezone.utc)


class BinanceTranslator:
    """
    Static translator methods.  Each method accepts a raw Binance message dict
    and returns a domain entity.  Raises ValueError on malformed input.
    """

    @staticmethod
    def to_ticker(data: dict) -> Ticker:
        """
        Binance 24hrTicker stream payload.
        Key fields: s, c, P, p, v, q, h, l, o, O, C
        """
        symbol = _normalize_symbol(data["s"])
        return Ticker(
            symbol=symbol,
            last_price=data["c"],
            price_change=data["p"],
            price_change_percent=data["P"],
            volume=data["v"],
            quote_volume=data["q"],
            high=data["h"],
            low=data["l"],
            open_price=data["o"],
            open_time=int(data["O"]),
            close_time=int(data["C"]),
            timestamp=_ms_to_datetime(int(data["C"])),  # closeTime as UTC datetime
        )

    @staticmethod
    def to_order_book(data: dict, raw_symbol: str) -> OrderBook:
        """
        Binance partial book depth stream payload.
        Key fields: lastUpdateId, bids (list of [price_str, qty_str]), asks
        raw_symbol: the stream prefix e.g. 'BTCUSDT'
        """
        symbol = _normalize_symbol(raw_symbol)
        bids = [
            OrderBookLevel(price=b[0], quantity=b[1])
            for b in data.get("bids", [])
        ]
        asks = [
            OrderBookLevel(price=a[0], quantity=a[1])
            for a in data.get("asks", [])
        ]
        # Enforce canonical ordering (compare as float for sort only — not stored)
        bids.sort(key=lambda x: float(x.price), reverse=True)
        asks.sort(key=lambda x: float(x.price))

        return OrderBook(
            symbol=symbol,
            bids=bids,
            asks=asks,
            last_update_id=int(data["lastUpdateId"]),
            timestamp=datetime.now(timezone.utc),  # ingestion time
        )

    @staticmethod
    def to_trade(data: dict) -> Trade:
        """
        Binance trade stream payload.
        Key fields: s, t, p, q, m, T
        """
        symbol = _normalize_symbol(data["s"])
        return Trade(
            symbol=symbol,
            trade_id=int(data["t"]),
            price=data["p"],
            quantity=data["q"],
            buyer_maker=bool(data["m"]),
            trade_time=int(data["T"]),
            timestamp=_ms_to_datetime(int(data["T"])),  # trade execution time as UTC datetime
        )

    @staticmethod
    def to_candle(data: dict) -> Candle:
        """
        Binance kline stream payload (nested under key 'k').
        Key fields within k: s, i, t, o, h, l, c, v, T, x
        """
        k = data.get("k") or data  # support both envelope and direct
        symbol = _normalize_symbol(k["s"])
        return Candle(
            symbol=symbol,
            interval=k["i"],
            open_time=int(k["t"]),
            open=k["o"],
            high=k["h"],
            low=k["l"],
            close=k["c"],
            volume=k["v"],
            close_time=int(k["T"]),
            is_closed=bool(k["x"]),
        )
