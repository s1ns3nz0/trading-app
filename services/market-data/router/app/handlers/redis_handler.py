"""
Redis writer for live market data.

Data structures (match design doc section 5):
  ticker:{symbol}            → Hash, TTL 60s
  orderbook:{symbol}:bids    → Sorted Set (score=price), TTL 10s
  orderbook:{symbol}:asks    → Sorted Set (score=price), TTL 10s
  trades:{symbol}            → List (LPUSH+LTRIM), TTL 300s
  ws:connections:{symbol}    → Set (connection IDs, no TTL here — managed by Lambda)

After writing, publishes to Redis pub/sub channel for WS Gateway push.
"""
from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis

from ..config import settings

logger = logging.getLogger(__name__)


class RedisMarketDataWriter:
    def __init__(self, redis: aioredis.Redis):
        self._redis = redis

    async def write_ticker(self, payload: dict) -> None:
        symbol = payload["symbol"]
        key = f"ticker:{symbol}"

        # Atomic pipeline: HSET + EXPIRE
        async with self._redis.pipeline(transaction=True) as pipe:
            hash_data = {k: v for k, v in payload.items() if k != "symbol"}
            pipe.hset(key, mapping=hash_data)
            pipe.expire(key, settings.ticker_ttl)
            await pipe.execute()

        # Pub/Sub push for connected WS clients
        channel = f"ws:ticker:{symbol}"
        await self._redis.publish(channel, json.dumps({"type": "ticker", "symbol": symbol, "data": hash_data}))

    async def write_orderbook(self, payload: dict) -> None:
        symbol = payload["symbol"]
        bids_key = f"orderbook:{symbol}:bids"
        asks_key = f"orderbook:{symbol}:asks"

        async with self._redis.pipeline(transaction=True) as pipe:
            # Replace entire orderbook atomically
            pipe.delete(bids_key, asks_key)

            for bid in payload.get("bids", []):
                price, qty = float(bid[0]), bid[1]
                # score = price (sorted set naturally orders bids desc via ZREVRANGE)
                pipe.zadd(bids_key, {json.dumps({"qty": qty}): price})

            for ask in payload.get("asks", []):
                price, qty = float(ask[0]), ask[1]
                pipe.zadd(asks_key, {json.dumps({"qty": qty}): price})

            pipe.expire(bids_key, settings.orderbook_ttl)
            pipe.expire(asks_key, settings.orderbook_ttl)
            await pipe.execute()

        channel = f"ws:orderbook:{symbol}"
        book_data = {"bids": payload.get("bids", []), "asks": payload.get("asks", [])}
        await self._redis.publish(channel, json.dumps({"type": "orderbook", "symbol": symbol, "data": book_data}))

    async def write_trade(self, payload: dict) -> None:
        symbol = payload["symbol"]
        key = f"trades:{symbol}"

        trade_entry = json.dumps({
            "id":         payload["tradeId"],
            "price":      payload["price"],
            "qty":        payload["qty"],
            "buyerMaker": payload["buyerMaker"],
            "time":       payload["tradeTime"],
        })

        async with self._redis.pipeline(transaction=True) as pipe:
            pipe.lpush(key, trade_entry)
            pipe.ltrim(key, 0, settings.trades_max_length - 1)
            pipe.expire(key, settings.trades_ttl)
            await pipe.execute()

        channel = f"ws:trade:{symbol}"
        await self._redis.publish(channel, json.dumps({"type": "trade", "symbol": symbol, "data": json.loads(trade_entry)}))
