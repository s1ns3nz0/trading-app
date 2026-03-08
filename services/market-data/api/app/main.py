"""
Market Data REST API — entry point.
Endpoints: /market/ticker, /market/orderbook, /market/trades, /market/candles, /market/symbols
"""
import logging
import sys

import boto3
import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import router

logging.basicConfig(
    level=settings.log_level,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)

app = FastAPI(title="MarketData REST API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
async def startup():
    app.state.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
    app.state.ddb_table = ddb.Table(settings.candles_table)


@app.on_event("shutdown")
async def shutdown():
    await app.state.redis.aclose()


@app.get("/health")
async def health():
    return {"status": "ok"}
