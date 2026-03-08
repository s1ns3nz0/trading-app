"""
Binance WebSocket combined stream client.
Handles connection, ACL translation, and dispatch to Kafka producer callbacks.
Reconnects with exponential backoff on any connection failure.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
from typing import Callable, Awaitable

import websockets
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from ..acl import BinanceTranslator
from ..config import settings
from ..models.market_data import Ticker, OrderBook, Trade, Candle

logger = logging.getLogger(__name__)

OnTickerCallback   = Callable[[Ticker], Awaitable[None]]
OnOrderBookCallback = Callable[[OrderBook], Awaitable[None]]
OnTradeCallback    = Callable[[Trade], Awaitable[None]]
OnCandleCallback   = Callable[[Candle], Awaitable[None]]


class BinanceStream:
    """
    Combined stream client for Binance WebSocket API.

    Usage:
        stream = BinanceStream(
            on_ticker=producer.publish_ticker,
            on_orderbook=producer.publish_orderbook,
            on_trade=producer.publish_trade,
            on_candle=producer.publish_candle,
        )
        await stream.run_forever()
    """

    def __init__(
        self,
        on_ticker: OnTickerCallback,
        on_orderbook: OnOrderBookCallback,
        on_trade: OnTradeCallback,
        on_candle: OnCandleCallback,
    ):
        self._on_ticker    = on_ticker
        self._on_orderbook = on_orderbook
        self._on_trade     = on_trade
        self._on_candle    = on_candle

    def _build_url(self) -> str:
        streams = "/".join(settings.binance_stream_names)
        return f"{settings.binance_ws_base_url}/stream?streams={streams}"

    async def run_forever(self) -> None:
        """Connect to Binance WS and process messages indefinitely.  Reconnects on error."""
        attempt = 0
        while True:
            url = self._build_url()
            logger.info("Connecting to Binance stream (attempt=%d) url=%s", attempt + 1, url[:80])
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=10,
                    max_size=2**20,  # 1 MiB max message
                ) as ws:
                    logger.info("Connected to Binance combined stream (%d streams)", len(settings.binance_stream_names))
                    attempt = 0  # reset on successful connection
                    async for raw in ws:
                        await self._dispatch(json.loads(raw))

            except ConnectionClosedOK:
                logger.info("Binance WS closed cleanly — reconnecting")
            except ConnectionClosedError as e:
                logger.warning("Binance WS connection error: %s — reconnecting", e)
            except Exception as e:
                logger.exception("Unexpected error in Binance stream: %s", e)

            # Exponential backoff with jitter
            wait = min(
                settings.reconnect_min_wait * (2 ** attempt),
                settings.reconnect_max_wait,
            )
            logger.info("Reconnecting in %.1fs", wait)
            await asyncio.sleep(wait)
            attempt += 1

    async def _dispatch(self, envelope: dict) -> None:
        """Route a combined stream envelope to the appropriate handler."""
        stream: str = envelope.get("stream", "")
        data: dict  = envelope.get("data", {})

        if not stream or not data:
            return

        try:
            if "@ticker" in stream:
                ticker = BinanceTranslator.to_ticker(data)
                await self._on_ticker(ticker)

            elif "@depth" in stream:
                # stream name: btcusdt@depth20@100ms → extract "BTCUSDT"
                raw_symbol = stream.split("@")[0].upper()
                orderbook = BinanceTranslator.to_order_book(data, raw_symbol)
                await self._on_orderbook(orderbook)

            elif "@trade" in stream:
                trade = BinanceTranslator.to_trade(data)
                await self._on_trade(trade)

            elif "@kline" in stream:
                candle = BinanceTranslator.to_candle(data)
                await self._on_candle(candle)

        except (KeyError, ValueError) as e:
            logger.error("ACL translation failed for stream=%s: %s", stream, e)
        except Exception:
            logger.exception("Dispatch error for stream=%s", stream)
