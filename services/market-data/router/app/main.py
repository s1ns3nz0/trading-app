"""
Event Router — entry point.

Consumes Kafka topics and fans out to:
  - Redis (ticker, orderbook, trades)
  - EventBridge (cross-account events for downstream services)
"""
import asyncio
import logging
import signal
import sys

import redis.asyncio as aioredis

from .config import settings
from .consumers import MarketDataConsumer
from .handlers import RedisMarketDataWriter, EventBridgePublisher

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

TOPIC_HANDLERS = {
    "market.ticker.v1":    "write_ticker",
    "market.orderbook.v1": "write_orderbook",
    "market.trades.v1":    "write_trade",
}


async def main() -> None:
    logger.info("Starting event router | topics=%s", settings.topic_list)

    redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    redis_writer = RedisMarketDataWriter(redis_client)
    eb_publisher = EventBridgePublisher()

    async def handle_message(topic: str, payload: dict) -> None:
        method_name = TOPIC_HANDLERS.get(topic)
        if method_name:
            await getattr(redis_writer, method_name)(payload)
        await eb_publisher.publish(topic, payload)

    consumer = MarketDataConsumer(on_message=handle_message)
    await consumer.start()

    # Graceful shutdown
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: shutdown_event.set())

    consume_task = asyncio.create_task(consumer.consume())

    await shutdown_event.wait()
    consume_task.cancel()
    try:
        await consume_task
    except asyncio.CancelledError:
        pass

    await consumer.stop()
    await redis_client.aclose()
    logger.info("Router shut down cleanly")


if __name__ == "__main__":
    asyncio.run(main())
