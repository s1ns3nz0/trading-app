from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI

from .config import settings
from .producers.eventbridge_producer import EventBridgeProducer
from .routers import deposits, webhooks
from .services.deposit_service import DepositService
from .services.step_fn_service import StepFnService
from .services.wallet_service import WalletService

logger = logging.getLogger(__name__)

db_pool: asyncpg.Pool | None = None
deposit_svc: DepositService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, deposit_svc

    db_pool = await asyncpg.create_pool(
        settings.db_url, min_size=3, max_size=15
    )

    wallet_svc = WalletService()
    step_fn_svc = StepFnService()
    eb_producer = EventBridgeProducer()

    deposit_svc = DepositService(
        repo=None,  # injected per request via db_pool
        wallet_svc=wallet_svc,
        step_fn_svc=step_fn_svc,
    )

    logger.info("DepositService started")
    yield

    await db_pool.close()


app = FastAPI(title="DepositService", version="1.0.0", lifespan=lifespan)
app.include_router(deposits.router)
app.include_router(webhooks.router)


@app.get("/health")
async def health():
    return {"status": "ok", "db": db_pool is not None}
