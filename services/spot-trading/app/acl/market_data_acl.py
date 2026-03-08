"""
Anti-Corruption Layer: consumes market.ticker.v1 Kafka topic → internal PriceSnapshot.
SpotTrading never imports MarketData domain types or touches Binance directly.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Optional

from aiokafka import AIOKafkaConsumer

from ..config import settings
from ..models.domain import PriceSnapshot

logger = logging.getLogger(__name__)

_PRICE_DEVIATION_THRESHOLD = Decimal("0.10")  # 10% sanity check (R-05)


class MarketDataACL:
    """
    Background task that maintains an in-process price cache.
    Order API queries this cache for price sanity validation on LIMIT orders.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, PriceSnapshot] = {}
        self._consumer: Optional[AIOKafkaConsumer] = None
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            "market.ticker.v1",
            bootstrap_servers=settings.kafka_brokers,
            group_id="spot-trading-market-acl",
            value_deserializer=lambda v: json.loads(v.decode()),
            auto_offset_reset="latest",
        )
        await self._consumer.start()
        self._task = asyncio.create_task(self._consume_loop())
        logger.info("MarketDataACL consumer started")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._consumer:
            await self._consumer.stop()
        logger.info("MarketDataACL consumer stopped")

    async def _consume_loop(self) -> None:
        try:
            async for msg in self._consumer:
                try:
                    snapshot = self._translate(msg.value)
                    self._cache[snapshot.symbol] = snapshot
                except (KeyError, Exception) as exc:
                    logger.warning("MarketDataACL translation error: %s", exc)
        except asyncio.CancelledError:
            pass

    @staticmethod
    def _translate(payload: dict) -> PriceSnapshot:
        return PriceSnapshot(
            symbol=payload["symbol"],
            last_price=Decimal(payload["lastPrice"]),
            high_24h=Decimal(payload["high"]),
            low_24h=Decimal(payload["low"]),
            updated_at=datetime.fromisoformat(payload["timestamp"]).replace(tzinfo=timezone.utc),
        )

    def get_snapshot(self, symbol: str) -> Optional[PriceSnapshot]:
        return self._cache.get(symbol)

    def validate_price(self, symbol: str, order_price: Decimal) -> bool:
        """
        Sanity check: order price must be within ±10% of last traded price.
        Called only for LIMIT orders. Fails-open if no snapshot yet (startup).
        """
        snap = self._cache.get(symbol)
        if snap is None:
            return True  # fail-open during warm-up period
        deviation = abs(order_price - snap.last_price) / snap.last_price
        return deviation <= _PRICE_DEVIATION_THRESHOLD
