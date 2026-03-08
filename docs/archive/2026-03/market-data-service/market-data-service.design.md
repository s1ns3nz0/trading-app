# Design: market-data-service

> **Feature**: market-data-service
> **Created**: 2026-03-08
> **Phase**: Design
> **References**: `docs/01-plan/features/market-data-service.plan.md`

---

## 1. Service Directory Structure

```
services/market-data/
├── ingester/                    # Feed Ingester — Binance WS → Kafka
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── acl/
│   │   │   ├── __init__.py
│   │   │   └── binance_translator.py   # ACL: Binance → domain model
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── market_data.py          # Domain entities (Ticker, OrderBook, Trade)
│   │   ├── producers/
│   │   │   ├── __init__.py
│   │   │   └── kafka_producer.py       # aiokafka async producer
│   │   └── streams/
│   │       ├── __init__.py
│   │       └── binance_stream.py       # WS connection + reconnect logic
│   ├── Dockerfile
│   └── requirements.txt
│
├── router/                      # Event Router — Kafka → Redis + EventBridge
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── consumers/
│   │   │   ├── __init__.py
│   │   │   └── kafka_consumer.py       # aiokafka consumer group
│   │   └── handlers/
│   │       ├── __init__.py
│   │       ├── redis_handler.py        # Write ticker/orderbook/trades to Redis
│   │       └── eventbridge_handler.py  # Publish cross-account events
│   ├── Dockerfile
│   └── requirements.txt
│
├── api/                         # REST API — ticker, orderbook, candles
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   └── routers/
│   │       ├── __init__.py
│   │       ├── ticker.py
│   │       ├── orderbook.py
│   │       ├── trades.py
│   │       ├── candles.py
│   │       └── symbols.py
│   ├── Dockerfile
│   └── requirements.txt
│
├── candle-builder/              # Lambda — Kafka trigger → OHLCV DynamoDB
│   ├── handler.py
│   └── requirements.txt
│
├── ws-gateway/                  # Lambda — API GW WebSocket handlers
│   ├── connect.py
│   ├── disconnect.py
│   ├── default.py               # Routes subscribe/unsubscribe actions
│   └── requirements.txt
│
└── infra/
    ├── main.tf                  # ECS cluster, MSK, Redis, DynamoDB, API GW
    ├── variables.tf
    └── outputs.tf
```

---

## 2. Domain Models

### `services/market-data/ingester/app/models/market_data.py`

```python
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import StrEnum
from typing import Optional


class Interval(StrEnum):
    ONE_MINUTE   = "1m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    ONE_HOUR     = "1h"
    FOUR_HOURS   = "4h"
    ONE_DAY      = "1d"


@dataclass(frozen=True)
class Symbol:
    value: str  # normalized: "BTC-USDT"

    def __post_init__(self):
        if "-" not in self.value:
            raise ValueError(f"Symbol must be normalized with dash: {self.value}")

    def to_binance(self) -> str:
        """BTC-USDT → BTCUSDT"""
        return self.value.replace("-", "")


@dataclass
class Ticker:
    symbol: str
    last_price: str
    price_change: str
    price_change_percent: str
    volume: str
    quote_volume: str
    high: str
    low: str
    open_price: str
    open_time: int   # epoch ms
    close_time: int  # epoch ms
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_kafka_payload(self) -> dict:
        return {
            "symbol": self.symbol,
            "lastPrice": self.last_price,
            "priceChange": self.price_change,
            "priceChangePercent": self.price_change_percent,
            "volume": self.volume,
            "quoteVolume": self.quote_volume,
            "high": self.high,
            "low": self.low,
            "openPrice": self.open_price,
            "openTime": self.open_time,
            "closeTime": self.close_time,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class OrderBookLevel:
    price: str
    quantity: str


@dataclass
class OrderBook:
    symbol: str
    bids: list[OrderBookLevel]  # top 20, sorted descending by price
    asks: list[OrderBookLevel]  # top 20, sorted ascending by price
    last_update_id: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_kafka_payload(self) -> dict:
        return {
            "symbol": self.symbol,
            "bids": [[b.price, b.quantity] for b in self.bids],
            "asks": [[a.price, a.quantity] for a in self.asks],
            "lastUpdateId": self.last_update_id,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class Trade:
    symbol: str
    trade_id: int
    price: str
    quantity: str
    buyer_maker: bool  # True = sell, False = buy
    trade_time: int    # epoch ms
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_kafka_payload(self) -> dict:
        return {
            "symbol": self.symbol,
            "tradeId": self.trade_id,
            "price": self.price,
            "quantity": self.quantity,
            "buyerMaker": self.buyer_maker,
            "tradeTime": self.trade_time,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class Candle:
    symbol: str
    interval: str
    open_time: int
    open: str
    high: str
    low: str
    close: str
    volume: str
    close_time: int
    is_closed: bool  # True = bar is complete (not in-progress)
```

---

## 3. Anti-Corruption Layer

### `services/market-data/ingester/app/acl/binance_translator.py`

```python
"""
ACL: Translate Binance WebSocket stream messages into domain models.
No Binance types ever leave this module.
"""

from ..models.market_data import Ticker, OrderBook, OrderBookLevel, Trade, Candle


class BinanceTranslator:

    @staticmethod
    def normalize_symbol(binance_symbol: str) -> str:
        """BTCUSDT → BTC-USDT  (naive split on USDT/BUSD/BTC/ETH suffixes)"""
        for quote in ("USDT", "BUSD", "BTC", "ETH", "BNB"):
            if binance_symbol.endswith(quote):
                base = binance_symbol[: -len(quote)]
                return f"{base}-{quote}"
        return binance_symbol  # fallback — leave as-is

    @classmethod
    def to_ticker(cls, msg: dict) -> Ticker:
        """Translate 24hr ticker stream message (stream: !miniTicker@arr or <symbol>@ticker)"""
        return Ticker(
            symbol=cls.normalize_symbol(msg["s"]),
            last_price=msg["c"],
            price_change=msg["p"],
            price_change_percent=msg["P"],
            volume=msg["v"],
            quote_volume=msg["q"],
            high=msg["h"],
            low=msg["l"],
            open_price=msg["o"],
            open_time=msg["O"],
            close_time=msg["C"],
        )

    @classmethod
    def to_order_book(cls, msg: dict, symbol: str) -> OrderBook:
        """Translate partial depth stream (@depth20@100ms)"""
        return OrderBook(
            symbol=cls.normalize_symbol(symbol),
            bids=[OrderBookLevel(price=b[0], quantity=b[1]) for b in msg["bids"][:20]],
            asks=[OrderBookLevel(price=a[0], quantity=a[1]) for a in msg["asks"][:20]],
            last_update_id=msg["lastUpdateId"],
        )

    @classmethod
    def to_trade(cls, msg: dict) -> Trade:
        """Translate trade stream (@trade)"""
        return Trade(
            symbol=cls.normalize_symbol(msg["s"]),
            trade_id=msg["t"],
            price=msg["p"],
            quantity=msg["q"],
            buyer_maker=msg["m"],
            trade_time=msg["T"],
        )

    @classmethod
    def to_candle(cls, msg: dict) -> Candle:
        """Translate kline stream (@kline_1m)"""
        k = msg["k"]
        return Candle(
            symbol=cls.normalize_symbol(msg["s"]),
            interval=k["i"],
            open_time=k["t"],
            open=k["o"],
            high=k["h"],
            low=k["l"],
            close=k["c"],
            volume=k["v"],
            close_time=k["T"],
            is_closed=k["x"],
        )
```

---

## 4. Feed Ingester

### `services/market-data/ingester/app/streams/binance_stream.py`

```python
"""
Binance WebSocket combined stream ingester.
Connects to wss://stream.binance.com:9443/stream?streams=...
with automatic reconnection and exponential backoff.
"""

import asyncio
import json
import logging
from typing import Callable, Awaitable

import websockets
from websockets.exceptions import ConnectionClosed

from ..acl.binance_translator import BinanceTranslator
from ..models.market_data import Ticker, OrderBook, Trade

logger = logging.getLogger(__name__)

# Binance combined stream — one connection for all subscriptions
BINANCE_WS_URL = "wss://stream.binance.com:9443/stream"

MessageHandler = Callable[[dict], Awaitable[None]]


class BinanceStream:
    def __init__(
        self,
        symbols: list[str],
        on_ticker: MessageHandler,
        on_orderbook: MessageHandler,
        on_trade: MessageHandler,
        on_candle: MessageHandler,
    ):
        self._symbols = symbols  # normalized: ["BTC-USDT", "ETH-USDT"]
        self._on_ticker = on_ticker
        self._on_orderbook = on_orderbook
        self._on_trade = on_trade
        self._on_candle = on_candle
        self._reconnect_attempts = 0
        self._max_reconnect_delay = 60  # seconds

    def _build_stream_url(self) -> str:
        streams = []
        for sym in self._symbols:
            binance = sym.replace("-", "").lower()
            streams += [
                f"{binance}@ticker",
                f"{binance}@depth20@100ms",
                f"{binance}@trade",
                f"{binance}@kline_1m",
            ]
        return f"{BINANCE_WS_URL}?streams={'/'.join(streams)}"

    async def run_forever(self):
        while True:
            try:
                await self._connect()
                self._reconnect_attempts = 0
            except Exception as e:
                delay = min(2 ** self._reconnect_attempts, self._max_reconnect_delay)
                logger.warning(f"Stream disconnected: {e}. Reconnecting in {delay}s...")
                self._reconnect_attempts += 1
                await asyncio.sleep(delay)

    async def _connect(self):
        url = self._build_stream_url()
        logger.info(f"Connecting to Binance stream: {url[:80]}...")

        async with websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=10,
            max_size=10 * 1024 * 1024,  # 10MB
        ) as ws:
            logger.info("Connected to Binance WebSocket")
            async for raw_message in ws:
                await self._dispatch(json.loads(raw_message))

    async def _dispatch(self, envelope: dict):
        stream: str = envelope.get("stream", "")
        data: dict = envelope.get("data", {})

        if not stream or not data:
            return

        try:
            if "@ticker" in stream:
                ticker = BinanceTranslator.to_ticker(data)
                await self._on_ticker(ticker)
            elif "@depth" in stream:
                symbol = stream.split("@")[0].upper()
                orderbook = BinanceTranslator.to_order_book(data, symbol)
                await self._on_orderbook(orderbook)
            elif "@trade" in stream:
                trade = BinanceTranslator.to_trade(data)
                await self._on_trade(trade)
            elif "@kline" in stream:
                candle = BinanceTranslator.to_candle(data)
                await self._on_candle(candle)
        except Exception as e:
            logger.error(f"Failed to dispatch message from stream {stream}: {e}")
```

---

## 5. Kafka Producer

### `services/market-data/ingester/app/producers/kafka_producer.py`

```python
import json
import logging
from aiokafka import AIOKafkaProducer
from ..config import settings

logger = logging.getLogger(__name__)

TOPICS = {
    "ticker":    "market.ticker.v1",
    "orderbook": "market.orderbook.v1",
    "trade":     "market.trades.v1",
    "candle":    "market.candles.1m.v1",
}


class MarketDataProducer:
    def __init__(self):
        self._producer: AIOKafkaProducer | None = None

    async def start(self):
        self._producer = AIOKafkaProducer(
            bootstrap_servers=settings.kafka_brokers,
            value_serializer=lambda v: json.dumps(v).encode(),
            # Partition by symbol for ordering within a symbol
            key_serializer=lambda k: k.encode() if k else None,
            compression_type="lz4",
            acks="all",          # wait for all ISR replicas
            max_batch_size=32768,
            linger_ms=5,         # small batch delay for throughput
        )
        await self._producer.start()
        logger.info("Kafka producer started")

    async def stop(self):
        if self._producer:
            await self._producer.stop()

    async def publish_ticker(self, ticker) -> None:
        await self._producer.send(
            TOPICS["ticker"],
            key=ticker.symbol,
            value=ticker.to_kafka_payload(),
        )

    async def publish_orderbook(self, orderbook) -> None:
        await self._producer.send(
            TOPICS["orderbook"],
            key=orderbook.symbol,
            value=orderbook.to_kafka_payload(),
        )

    async def publish_trade(self, trade) -> None:
        await self._producer.send(
            TOPICS["trade"],
            key=trade.symbol,
            value=trade.to_kafka_payload(),
        )

    async def publish_candle(self, candle) -> None:
        if candle.is_closed:  # only publish complete bars
            payload = {
                "symbol": candle.symbol,
                "interval": candle.interval,
                "openTime": candle.open_time,
                "open": candle.open,
                "high": candle.high,
                "low": candle.low,
                "close": candle.close,
                "volume": candle.volume,
                "closeTime": candle.close_time,
            }
            await self._producer.send(
                TOPICS["candle"], key=candle.symbol, value=payload
            )
```

---

## 6. Redis Handler

### `services/market-data/router/app/handlers/redis_handler.py`

```python
"""
Write market data domain objects into Redis data structures.
Uses pipeline for atomic multi-key updates.
"""

import json
from redis.asyncio import Redis
from ..config import settings

TICKER_TTL = 60       # seconds
ORDERBOOK_TTL = 10
TRADES_TTL = 300
TRADES_MAX_LEN = 50


class RedisMarketDataWriter:
    def __init__(self, redis: Redis):
        self._redis = redis

    async def write_ticker(self, payload: dict) -> None:
        symbol = payload["symbol"]
        key = f"ticker:{symbol}"
        async with self._redis.pipeline(transaction=False) as pipe:
            pipe.hset(key, mapping={k: str(v) for k, v in payload.items()})
            pipe.expire(key, TICKER_TTL)
            await pipe.execute()

    async def write_orderbook(self, payload: dict) -> None:
        symbol = payload["symbol"]
        bids_key = f"orderbook:{symbol}:bids"
        asks_key = f"orderbook:{symbol}:asks"

        async with self._redis.pipeline(transaction=False) as pipe:
            # Delete + re-add for clean snapshot (sorted set: score=price float)
            pipe.delete(bids_key, asks_key)
            for price, qty in payload["bids"]:
                pipe.zadd(bids_key, {json.dumps({"price": price, "qty": qty}): float(price)})
            for price, qty in payload["asks"]:
                pipe.zadd(asks_key, {json.dumps({"price": price, "qty": qty}): float(price)})
            pipe.expire(bids_key, ORDERBOOK_TTL)
            pipe.expire(asks_key, ORDERBOOK_TTL)
            await pipe.execute()

    async def write_trade(self, payload: dict) -> None:
        symbol = payload["symbol"]
        key = f"trades:{symbol}"
        async with self._redis.pipeline(transaction=False) as pipe:
            pipe.lpush(key, json.dumps(payload))
            pipe.ltrim(key, 0, TRADES_MAX_LEN - 1)
            pipe.expire(key, TRADES_TTL)
            await pipe.execute()

    async def push_to_subscribers(self, channel: str, symbol: str, payload: dict) -> None:
        """Publish to a Redis pub/sub channel for WS gateway fan-out."""
        await self._redis.publish(f"ws:{channel}:{symbol}", json.dumps(payload))
```

---

## 7. REST API

### `services/market-data/api/app/routers/candles.py`

```python
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
import boto3
from boto3.dynamodb.conditions import Key

router = APIRouter()

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("market-data-candles")


class CandleResponse(BaseModel):
    symbol: str
    interval: str
    openTime: int
    open: str
    high: str
    low: str
    close: str
    volume: str
    closeTime: int


@router.get("/candles/{symbol}", response_model=list[CandleResponse])
async def get_candles(
    symbol: str,
    interval: str = Query("1m", pattern="^(1m|5m|15m|1h|4h|1d)$"),
    limit: int = Query(200, ge=1, le=1000),
    start_time: int | None = Query(None, alias="startTime"),
):
    """
    Return OHLCV candles from DynamoDB.
    PK = CANDLE#{symbol}#{interval}, SK = openTime (epoch ms)
    """
    pk = f"CANDLE#{symbol.upper()}#{interval}"

    key_condition = Key("PK").eq(pk)
    if start_time:
        key_condition &= Key("SK").gte(start_time)

    response = table.query(
        KeyConditionExpression=key_condition,
        ScanIndexForward=True,
        Limit=limit,
    )

    items = response.get("Items", [])
    if not items:
        raise HTTPException(status_code=404, detail=f"No candles found for {symbol}/{interval}")

    return [
        CandleResponse(
            symbol=symbol,
            interval=interval,
            openTime=int(item["SK"]),
            open=item["open"],
            high=item["high"],
            low=item["low"],
            close=item["close"],
            volume=item["volume"],
            closeTime=int(item["closeTime"]),
        )
        for item in items
    ]
```

### `services/market-data/api/app/routers/ticker.py`

```python
from fastapi import APIRouter, HTTPException
from redis.asyncio import Redis
from pydantic import BaseModel
from ..config import get_redis

router = APIRouter()


class TickerResponse(BaseModel):
    symbol: str
    lastPrice: str
    priceChange: str
    priceChangePercent: str
    volume: str
    high: str
    low: str
    openPrice: str
    closeTime: int


@router.get("/ticker/{symbol}", response_model=TickerResponse)
async def get_ticker(symbol: str, redis: Redis = get_redis):
    data = await redis.hgetall(f"ticker:{symbol.upper()}")
    if not data:
        raise HTTPException(status_code=404, detail=f"No ticker data for {symbol}")
    return TickerResponse(
        symbol=data["symbol"],
        lastPrice=data["lastPrice"],
        priceChange=data["priceChange"],
        priceChangePercent=data["priceChangePercent"],
        volume=data["volume"],
        high=data["high"],
        low=data["low"],
        openPrice=data["openPrice"],
        closeTime=int(data["closeTime"]),
    )
```

---

## 8. WebSocket Gateway Lambdas

### `services/market-data/ws-gateway/connect.py`

```python
"""$connect handler — store connection ID + symbol subscription in DynamoDB."""
import boto3, os, json

ddb = boto3.resource("dynamodb")
table = ddb.Table(os.environ["CONNECTIONS_TABLE"])


def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    table.put_item(Item={
        "connectionId": connection_id,
        "subscriptions": [],
        "ttl": int(__import__("time").time()) + 86400,  # 24h TTL
    })
    return {"statusCode": 200}
```

### `services/market-data/ws-gateway/default.py`

```python
"""
$default handler — routes subscribe/unsubscribe actions.
Pushes live data from Redis pub/sub to API GW connections.
"""
import asyncio
import boto3
import json
import os
import redis.asyncio as aioredis

REDIS_URL = os.environ["REDIS_URL"]
CONNECTIONS_TABLE = os.environ["CONNECTIONS_TABLE"]
API_GW_ENDPOINT = os.environ["API_GW_ENDPOINT"]

apigw = boto3.client("apigatewaymanagementapi", endpoint_url=API_GW_ENDPOINT)
ddb = boto3.resource("dynamodb")
table = ddb.Table(CONNECTIONS_TABLE)


def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    body = json.loads(event.get("body") or "{}")

    action = body.get("action")
    channel = body.get("channel")   # ticker | orderbook | trade
    symbol = body.get("symbol", "").upper()

    if action == "subscribe" and channel and symbol:
        # Store subscription
        table.update_item(
            Key={"connectionId": connection_id},
            UpdateExpression="ADD subscriptions :s",
            ExpressionAttributeValues={":s": {f"{channel}:{symbol}"}},
        )
        # Send snapshot from Redis immediately
        asyncio.run(_push_snapshot(connection_id, channel, symbol))

    elif action == "unsubscribe" and channel and symbol:
        table.update_item(
            Key={"connectionId": connection_id},
            UpdateExpression="DELETE subscriptions :s",
            ExpressionAttributeValues={":s": {f"{channel}:{symbol}"}},
        )

    return {"statusCode": 200}


async def _push_snapshot(connection_id: str, channel: str, symbol: str):
    redis = await aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        if channel == "ticker":
            data = await redis.hgetall(f"ticker:{symbol}")
        elif channel == "orderbook":
            bids = await redis.zrevrange(f"orderbook:{symbol}:bids", 0, 19, withscores=False)
            asks = await redis.zrange(f"orderbook:{symbol}:asks", 0, 19, withscores=False)
            data = {"bids": [json.loads(b) for b in bids], "asks": [json.loads(a) for a in asks]}
        else:
            return

        if data:
            apigw.post_to_connection(
                ConnectionId=connection_id,
                Data=json.dumps({"type": channel, "symbol": symbol, "data": data}),
            )
    finally:
        await redis.aclose()
```

---

## 9. Candle Builder Lambda

### `services/market-data/candle-builder/handler.py`

```python
"""
Lambda triggered by MSK Kafka — consumes market.candles.1m.v1
and writes closed OHLCV bars to DynamoDB.
"""
import base64
import boto3
import json
import os
from decimal import Decimal

ddb = boto3.resource("dynamodb")
table = ddb.Table(os.environ["CANDLES_TABLE"])


def handler(event, context):
    for topic_partition, records in event["records"].items():
        for record in records:
            payload = json.loads(base64.b64decode(record["value"]).decode())
            _write_candle(payload)


def _write_candle(payload: dict):
    symbol = payload["symbol"]
    interval = payload["interval"]
    open_time = int(payload["openTime"])

    table.put_item(Item={
        "PK": f"CANDLE#{symbol}#{interval}",
        "SK": open_time,
        "GSI1PK": f"SYMBOL#{symbol}",
        "GSI1SK": f"{interval}#{open_time}",
        "open":      payload["open"],
        "high":      payload["high"],
        "low":       payload["low"],
        "close":     payload["close"],
        "volume":    payload["volume"],
        "closeTime": int(payload["closeTime"]),
        "symbol":    symbol,
        "interval":  interval,
    })
```

---

## 10. Infrastructure Terraform

### `services/market-data/infra/main.tf`

```hcl
# Uses account-factory module (same pattern as spot-trading)
module "account" {
  source = "../../../infra/modules/account-factory"

  account_name = "market-data-prod"
  environment  = "prod"
  domain       = "MarketData"
  cost_center  = "CC-MARKET"
  team         = "data"

  vpc_cidr             = "10.1.0.0/16"
  private_subnet_cidrs = ["10.1.0.0/19", "10.1.32.0/19", "10.1.64.0/19"]
  public_subnet_cidrs  = ["10.1.128.0/20", "10.1.144.0/20", "10.1.160.0/20"]
  transit_gateway_id   = var.transit_gateway_id_prod
  org_id               = var.org_id
  log_archive_bucket   = var.log_archive_bucket
}

# ECS Cluster
resource "aws_ecs_cluster" "market_data" {
  name = "market-data-prod"
  setting { name = "containerInsights" value = "enabled" }
  tags = local.tags
}

# MSK Kafka — 3 brokers, KRaft mode (no ZooKeeper)
resource "aws_msk_cluster" "market_data" {
  cluster_name           = "market-data-prod"
  kafka_version          = "3.7.x"
  number_of_broker_nodes = 3

  broker_node_group_info {
    instance_type   = "kafka.t3.small"
    client_subnets  = module.account.private_subnet_ids
    security_groups = [aws_security_group.msk.id]

    storage_info {
      ebs_storage_info { volume_size = 100 }
    }
  }

  encryption_info {
    encryption_in_transit { client_broker = "TLS" in_cluster = true }
    encryption_at_rest { data_volume_kms_key_id = module.account.kms_key_id }
  }

  client_authentication {
    sasl { iam = true }  # IAM auth — no plaintext credentials
  }

  tags = local.tags
}

# ElastiCache Redis — single shard (market data is ephemeral, no cluster mode needed)
resource "aws_elasticache_replication_group" "market_data" {
  replication_group_id = "market-data-prod"
  description          = "Live market data cache (ticker, orderbook)"
  node_type            = "cache.r7g.medium"
  num_node_groups      = 1
  replicas_per_node_group = 1

  engine_version             = "7.2"
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true
  kms_key_id                 = module.account.kms_key_arn
  automatic_failover_enabled = true

  subnet_group_name  = aws_elasticache_subnet_group.market_data.name
  security_group_ids = [aws_security_group.redis.id]

  tags = local.tags
}

# DynamoDB — candle history + WS connections
resource "aws_dynamodb_table" "candles" {
  name         = "market-data-candles"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  attribute { name = "PK"     type = "S" }
  attribute { name = "SK"     type = "N" }
  attribute { name = "GSI1PK" type = "S" }
  attribute { name = "GSI1SK" type = "S" }

  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }

  server_side_encryption { enabled = true kms_key_arn = module.account.kms_key_arn }
  point_in_time_recovery { enabled = true }
  tags = local.tags
}

resource "aws_dynamodb_table" "ws_connections" {
  name         = "market-data-ws-connections"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "connectionId"

  attribute { name = "connectionId" type = "S" }

  ttl { attribute_name = "ttl" enabled = true }
  tags = local.tags
}

# API Gateway WebSocket
resource "aws_apigatewayv2_api" "ws" {
  name                       = "market-data-ws-prod"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"
  tags                       = local.tags
}

resource "aws_apigatewayv2_stage" "ws" {
  api_id      = aws_apigatewayv2_api.ws.id
  name        = "prod"
  auto_deploy = true
}
```

---

## 11. Implementation Order

| Step | Action | File(s) |
|------|--------|---------|
| 1 | Terraform infra | `services/market-data/infra/main.tf` |
| 2 | Domain models + ACL | `ingester/app/models/`, `ingester/app/acl/` |
| 3 | Kafka producer | `ingester/app/producers/kafka_producer.py` |
| 4 | Binance stream + ingester main | `ingester/app/streams/`, `ingester/app/main.py` |
| 5 | Redis handler | `router/app/handlers/redis_handler.py` |
| 6 | Kafka consumer + router main | `router/app/consumers/`, `router/app/main.py` |
| 7 | Candle Builder Lambda | `candle-builder/handler.py` |
| 8 | REST API (candles, ticker, orderbook) | `api/app/routers/` |
| 9 | WS Gateway Lambdas | `ws-gateway/connect.py`, `disconnect.py`, `default.py` |
| 10 | Frontend env wiring | `apps/web/.env.local` — point `NEXT_PUBLIC_WS_URL` + `NEXT_PUBLIC_SPOT_API_URL` to real endpoints |

---

## 12. ECS Task Definition (Ingester)

```json
{
  "family": "market-data-ingester",
  "cpu": "512",
  "memory": "1024",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "executionRoleArn": "arn:aws:iam::ACCOUNT:role/ecsTaskExecutionRole",
  "taskRoleArn": "arn:aws:iam::ACCOUNT:role/market-data-ingester-task",
  "containerDefinitions": [
    {
      "name": "ingester",
      "image": "ACCOUNT.dkr.ecr.ap-northeast-2.amazonaws.com/market-data-ingester:latest",
      "environment": [
        { "name": "KAFKA_BROKERS", "value": "BROKER_1:9098,BROKER_2:9098,BROKER_3:9098" },
        { "name": "SYMBOLS", "value": "BTC-USDT,ETH-USDT,SOL-USDT,BNB-USDT" },
        { "name": "LOG_LEVEL", "value": "INFO" }
      ],
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/market-data-ingester",
          "awslogs-region": "ap-northeast-2",
          "awslogs-stream-prefix": "ecs"
        }
      },
      "healthCheck": {
        "command": ["CMD-SHELL", "python -c \"import asyncio; asyncio.run(__import__('aiohttp').ClientSession().get('http://localhost:8080/health'))\""],
        "interval": 30,
        "timeout": 5,
        "retries": 3
      }
    }
  ]
}
```

---

## 13. Requirements Files

### `services/market-data/ingester/requirements.txt`
```
fastapi==0.115.5
uvicorn[standard]==0.32.1
websockets==13.1
aiokafka==0.11.0
pydantic-settings==2.6.1
```

### `services/market-data/router/requirements.txt`
```
aiokafka==0.11.0
redis[asyncio]==5.2.0
boto3==1.35.76
pydantic-settings==2.6.1
```

### `services/market-data/api/requirements.txt`
```
fastapi==0.115.5
uvicorn[standard]==0.32.1
redis[asyncio]==5.2.0
boto3==1.35.76
pydantic==2.10.3
mangum==0.19.0
```

### `services/market-data/candle-builder/requirements.txt`
```
boto3==1.35.76
```

### `services/market-data/ws-gateway/requirements.txt`
```
boto3==1.35.76
redis[asyncio]==5.2.0
```
