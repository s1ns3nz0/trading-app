"""
Market Data Feed Ingester — entry point.

Lifecycle:
  1. Start Kafka producer
  2. Open Binance combined WebSocket stream
  3. For each message: ACL translate → publish to Kafka
  4. On disconnect: reconnect with exponential backoff (handled by BinanceStream)
"""
import asyncio
import logging
import signal
import sys

from .config import settings
from .producers import MarketDataProducer
from .streams import BinanceStream

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info(
        "Starting market-data ingester | symbols=%s | streams=%s",
        settings.symbol_list,
        len(settings.binance_stream_names),
    )

    producer = MarketDataProducer()
    await producer.start()

    stream = BinanceStream(
        on_ticker=producer.publish_ticker,
        on_orderbook=producer.publish_orderbook,
        on_trade=producer.publish_trade,
        on_candle=producer.publish_candle,
    )

    # Graceful shutdown
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()

    def _handle_signal():
        logger.info("Shutdown signal received")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal)

    stream_task = asyncio.create_task(stream.run_forever())

    await shutdown_event.wait()
    stream_task.cancel()
    try:
        await stream_task
    except asyncio.CancelledError:
        pass

    await producer.stop()
    logger.info("Ingester shut down cleanly")


if __name__ == "__main__":
    asyncio.run(main())
