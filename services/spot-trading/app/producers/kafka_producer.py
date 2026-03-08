from __future__ import annotations

import json
import logging

from aiokafka import AIOKafkaProducer

from ..config import settings
from ..models.domain import Order, Trade

logger = logging.getLogger(__name__)

TOPICS = {
    "order":    "spot.orders.v1",
    "trade":    "spot.trades.v1",
    "position": "spot.positions.v1",
}


class SpotKafkaProducer:
    def __init__(self) -> None:
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_brokers,
            value_serializer=lambda v: json.dumps(v).encode(),
            key_serializer=lambda k: k.encode() if k else None,
            acks="all",
            compression_type="lz4",
            retries=5,
        )
        await self._producer.start()
        logger.info("SpotKafkaProducer started")

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()
            logger.info("SpotKafkaProducer stopped")

    async def publish_order(self, order: Order) -> None:
        await self._send(TOPICS["order"], key=order.user_id, value=order.to_kafka_payload())

    async def publish_trade(self, trade: Trade) -> None:
        await self._send(TOPICS["trade"], key=trade.symbol, value=trade.to_kafka_payload())

    async def _send(self, topic: str, key: str, value: dict) -> None:
        if not self._producer:
            logger.error("Kafka producer not started")
            return
        try:
            # acks=all ensures message is durable before returning (R-04)
            await self._producer.send_and_wait(topic, key=key, value=value)
        except Exception as exc:
            logger.error("Kafka publish failed [%s]: %s", topic, exc)
            raise
