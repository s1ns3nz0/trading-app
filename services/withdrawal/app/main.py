from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI

from .config import settings
from .producers.eventbridge_producer import EventBridgeProducer
from .routers import withdrawals
from .services.aml_service import AMLService
from .services.step_fn_service import StepFnService
from .services.withdrawal_service import WithdrawalService

logger = logging.getLogger(__name__)

db_pool: asyncpg.Pool | None = None
withdrawal_svc: WithdrawalService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, withdrawal_svc

    db_pool = await asyncpg.create_pool(
        settings.db_url, min_size=3, max_size=15
    )

    aml_svc     = AMLService(repo=None)   # repo injected per request
    step_fn_svc = StepFnService()
    eb_producer = EventBridgeProducer()

    withdrawal_svc = WithdrawalService(
        repo=None,
        aml_svc=aml_svc,
        step_fn_svc=step_fn_svc,
    )

    logger.info("WithdrawalService started")
    yield

    await db_pool.close()


app = FastAPI(title="WithdrawalService", version="1.0.0", lifespan=lifespan)
app.include_router(withdrawals.router)


@app.get("/health")
async def health():
    return {"status": "ok", "db": db_pool is not None}
