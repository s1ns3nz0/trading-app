"""
Kafka consumer that fans out market events to Redis + EventBridge.
Uses aiokafka consumer group for parallel processing across router replicas.
"""
from __future__ import annotations

import json
import logging
from typing import Callable, Awaitable

from aiokafka import AIOKafkaConsumer
from aiokafka.errors import KafkaConnectionError

from ..config import settings

logger = logging.getLogger(__name__)

MessageHandler = Callable[[str, dict], Awaitable[None]]


class MarketDataConsumer:
    """
    Consumes market.ticker.v1, market.orderbook.v1, market.trades.v1
    and dispatches each message to the registered handler.
    """

    def __init__(self, on_message: MessageHandler):
        self._on_message = on_message
        self._consumer: AIOKafkaConsumer | None = None

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            *settings.topic_list,
            bootstrap_servers=settings.kafka_brokers,
            group_id=settings.kafka_consumer_group,
            value_deserializer=lambda b: json.loads(b.decode()),
            auto_offset_reset="latest",       # start from live data, not history
            enable_auto_commit=True,
            auto_commit_interval_ms=1000,
            fetch_max_bytes=52428800,          # 50 MiB
            max_poll_records=500,
        )
        await self._consumer.start()
        logger.info(
            "Kafka consumer started | group=%s | topics=%s",
            settings.kafka_consumer_group,
            settings.topic_list,
        )

    async def stop(self) -> None:
        if self._consumer:
            await self._consumer.stop()
            logger.info("Kafka consumer stopped")

    async def consume(self) -> None:
        """Process messages indefinitely.  Call after start()."""
        if not self._consumer:
            raise RuntimeError("Consumer not started")

        async for msg in self._consumer:
            try:
                await self._on_message(msg.topic, msg.value)
            except Exception:
                logger.exception(
                    "Handler error topic=%s partition=%d offset=%d",
                    msg.topic, msg.partition, msg.offset,
                )
