"""
Async Kafka producer for market data events.
Publishes to 4 topics partitioned by symbol for per-symbol ordering.
"""
from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from aiokafka import AIOKafkaProducer

from ..config import settings

if TYPE_CHECKING:
    from ..models.market_data import Ticker, OrderBook, Trade, Candle

logger = logging.getLogger(__name__)

TOPICS = {
    "ticker":    "market.ticker.v1",
    "orderbook": "market.orderbook.v1",
    "trade":     "market.trades.v1",
    "candle":    "market.candles.1m.v1",
}


class MarketDataProducer:
    """
    Wraps aiokafka AIOKafkaProducer.
    Use as an async context manager or call start()/stop() explicitly.
    """

    def __init__(self):
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_brokers,
            value_serializer=lambda v: json.dumps(v).encode(),
            key_serializer=lambda k: k.encode() if k else None,
            # Reliability: wait for all in-sync replicas
            acks="all",
            # Throughput: batch messages with a small delay
            compression_type="lz4",
            max_batch_size=32768,
            linger_ms=5,
            # Retry transient failures
            retries=5,
            retry_backoff_ms=200,
        )
        await self._producer.start()
        logger.info("Kafka producer connected to %s", settings.kafka_brokers)

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()
            logger.info("Kafka producer stopped")

    async def __aenter__(self) -> "MarketDataProducer":
        await self.start()
        return self

    async def __aexit__(self, *_) -> None:
        await self.stop()

    async def publish_ticker(self, ticker: "Ticker") -> None:
        await self._send(TOPICS["ticker"], key=ticker.symbol, value=ticker.to_kafka_payload())

    async def publish_orderbook(self, orderbook: "OrderBook") -> None:
        await self._send(TOPICS["orderbook"], key=orderbook.symbol, value=orderbook.to_kafka_payload())

    async def publish_trade(self, trade: "Trade") -> None:
        await self._send(TOPICS["trade"], key=trade.symbol, value=trade.to_kafka_payload())

    async def publish_candle(self, candle: "Candle") -> None:
        # Only publish closed (finalized) candles to candle topic
        if candle.is_closed:
            await self._send(TOPICS["candle"], key=candle.symbol, value=candle.to_kafka_payload())

    async def _send(self, topic: str, key: str, value: dict) -> None:
        if not self._producer:
            raise RuntimeError("Producer not started — call start() first")
        try:
            await self._producer.send(topic, key=key, value=value)
        except Exception:
            logger.exception("Failed to publish to topic=%s key=%s", topic, key)
            raise
