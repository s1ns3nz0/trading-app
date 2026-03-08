from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import asyncpg
import redis.asyncio as aioredis
from fastapi import FastAPI

from .acl.market_data_acl import MarketDataACL
from .config import settings
from .matching.engine import MatchingEngine
from .producers.kafka_producer import SpotKafkaProducer
from .repositories.order_repo import OrderRepository
from .routers import internal, orderbook, orders, positions, trades

logger = logging.getLogger(__name__)

# ── Application-level singletons ──────────────────────────────────────────────
market_acl   = MarketDataACL()
kafka_prod   = SpotKafkaProducer()
engines: dict[str, MatchingEngine] = {}
db_pool: asyncpg.Pool | None = None
redis_client: aioredis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, redis_client

    db_pool = await asyncpg.create_pool(settings.db_url, min_size=5, max_size=20)
    redis_client = await aioredis.from_url(settings.redis_url, decode_responses=True)

    await kafka_prod.start()
    await market_acl.start()

    # Bootstrap matching engines — rebuild order books from DB (R-03)
    async with db_pool.acquire() as conn:
        order_repo = OrderRepository(conn)
        for symbol in settings.supported_symbols:
            engine      = MatchingEngine(symbol)
            open_orders = await order_repo.list_open_by_symbol(symbol)
            engine.rebuild_from_orders(open_orders)
            engines[symbol] = engine
            logger.info("MatchingEngine[%s] rebuilt with %d open orders", symbol, len(open_orders))

    yield  # ── application running ──

    await market_acl.stop()
    await kafka_prod.stop()
    await redis_client.aclose()
    await db_pool.close()


app = FastAPI(title="SpotTradingService", version="1.0.0", lifespan=lifespan)
app.include_router(orders.router,    prefix="/spot")
app.include_router(trades.router,    prefix="/spot")
app.include_router(positions.router, prefix="/spot")
app.include_router(orderbook.router, prefix="/spot")
app.include_router(internal.router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "engines": list(engines.keys()),
        "db": db_pool is not None,
        "redis": redis_client is not None,
    }
