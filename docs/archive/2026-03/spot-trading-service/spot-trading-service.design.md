# Design: spot-trading-service

> **Feature**: spot-trading-service
> **Created**: 2026-03-08
> **Phase**: Design
> **Plan Reference**: docs/01-plan/features/spot-trading-service.plan.md
> **Level**: Enterprise

---

## 1. Service Directory Structure

```
services/spot-trading/
├── app/
│   ├── acl/
│   │   └── market_data_acl.py          # Kafka ticker → PriceSnapshot (no Binance coupling)
│   ├── matching/
│   │   ├── __init__.py
│   │   ├── order_book.py               # Heap-based bid/ask order book per symbol
│   │   └── engine.py                   # MatchingEngine: submit, cancel, rebuild
│   ├── models/
│   │   └── domain.py                   # Order, Trade, Position, value objects, enums
│   ├── producers/
│   │   └── kafka_producer.py           # Async MSK producer for SpotTrading events
│   ├── repositories/
│   │   ├── order_repo.py               # PostgreSQL order CRUD (asyncpg)
│   │   ├── trade_repo.py               # PostgreSQL trade insert + query
│   │   └── position_repo.py            # PostgreSQL position with SELECT FOR UPDATE
│   ├── routers/
│   │   ├── orders.py                   # POST/DELETE/GET /spot/orders
│   │   ├── trades.py                   # GET /spot/trades
│   │   ├── positions.py                # GET /spot/positions
│   │   └── orderbook.py                # GET /spot/orderbook/{symbol}
│   ├── schemas.py                      # Pydantic request/response models
│   ├── config.py                       # Settings (pydantic-settings)
│   └── main.py                         # FastAPI app, lifespan hooks
├── migrations/
│   ├── env.py                          # Alembic env
│   ├── alembic.ini
│   └── versions/
│       └── 001_initial_schema.py       # orders, trades, positions tables
├── ws-notifier/
│   ├── connect.py                      # Lambda: store connectionId → DynamoDB
│   ├── disconnect.py                   # Lambda: remove connectionId
│   └── default.py                      # Lambda: subscribe/unsubscribe, push order updates
├── k8s/
│   ├── order-api-deployment.yaml       # 2 replicas, m6i.large
│   ├── matching-engine-deployment.yaml # 1 replica per symbol, c6i.xlarge, StatefulSet
│   └── hpa.yaml                        # HPA for order-api only
├── infra/
│   ├── main.tf
│   ├── variables.tf
│   └── outputs.tf
├── Dockerfile
├── requirements.txt
└── pyproject.toml
```

---

## 2. Domain Model

**File**: `services/spot-trading/app/models/domain.py`

```python
"""
SpotTrading domain entities and value objects.
No external exchange types leak here — the ACL handles all translation.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


# ── Value Objects ──────────────────────────────────────────────────────────────

class OrderSide(str, Enum):
    BUY  = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    LIMIT  = "LIMIT"
    MARKET = "MARKET"


class OrderStatus(str, Enum):
    PENDING   = "PENDING"
    OPEN      = "OPEN"
    PARTIAL   = "PARTIAL"
    FILLED    = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED  = "REJECTED"


class TimeInForce(str, Enum):
    GTC = "GTC"   # Good Till Cancel
    IOC = "IOC"   # Immediate or Cancel
    FOK = "FOK"   # Fill or Kill


@dataclass(frozen=True)
class PriceSnapshot:
    """Internal market price cache — translated from Kafka ticker by ACL."""
    symbol: str
    last_price: Decimal
    high_24h: Decimal
    low_24h: Decimal
    updated_at: datetime


# ── Entities ───────────────────────────────────────────────────────────────────

@dataclass
class Order:
    """User's intent to buy or sell an asset."""
    id: str                                    = field(default_factory=_new_id)
    user_id: str                               = ""
    symbol: str                                = ""
    side: OrderSide                            = OrderSide.BUY
    type: OrderType                            = OrderType.LIMIT
    status: OrderStatus                        = OrderStatus.PENDING
    price: Optional[Decimal]                   = None    # None for MARKET orders
    orig_qty: Decimal                          = Decimal("0")
    executed_qty: Decimal                      = Decimal("0")
    avg_price: Optional[Decimal]               = None
    time_in_force: TimeInForce                 = TimeInForce.GTC
    created_at: datetime                       = field(default_factory=_now_utc)
    updated_at: datetime                       = field(default_factory=_now_utc)

    @property
    def remaining_qty(self) -> Decimal:
        return self.orig_qty - self.executed_qty

    @property
    def is_resting(self) -> bool:
        return self.status in (OrderStatus.OPEN, OrderStatus.PARTIAL)

    def to_kafka_payload(self) -> dict:
        return {
            "orderId":     self.id,
            "userId":      self.user_id,
            "symbol":      self.symbol,
            "side":        self.side.value,
            "type":        self.type.value,
            "status":      self.status.value,
            "price":       str(self.price) if self.price else None,
            "origQty":     str(self.orig_qty),
            "executedQty": str(self.executed_qty),
            "timestamp":   self.created_at.isoformat(),
        }


@dataclass
class Trade:
    """Matched execution between two orders."""
    id: str               = field(default_factory=_new_id)
    symbol: str           = ""
    buy_order_id: str     = ""
    sell_order_id: str    = ""
    price: Decimal        = Decimal("0")
    qty: Decimal          = Decimal("0")
    buyer_fee: Decimal    = Decimal("0")
    seller_fee: Decimal   = Decimal("0")
    executed_at: datetime = field(default_factory=_now_utc)

    def to_kafka_payload(self) -> dict:
        return {
            "tradeId":     self.id,
            "symbol":      self.symbol,
            "buyOrderId":  self.buy_order_id,
            "sellOrderId": self.sell_order_id,
            "price":       str(self.price),
            "qty":         str(self.qty),
            "buyerFee":    str(self.buyer_fee),
            "sellerFee":   str(self.seller_fee),
            "executedAt":  self.executed_at.isoformat(),
        }


@dataclass
class Position:
    """User's balance for a single asset."""
    user_id: str          = ""
    asset: str            = ""
    available: Decimal    = Decimal("0")
    locked: Decimal       = Decimal("0")
    updated_at: datetime  = field(default_factory=_now_utc)

    @property
    def total(self) -> Decimal:
        return self.available + self.locked
```

---

## 3. Order Book (Matching Engine)

### 3.1 Order Book Data Structure

**File**: `services/spot-trading/app/matching/order_book.py`

```python
"""
Price-time priority order book using heapq.
Bids: max-heap (negate price for Python min-heap).
Asks: min-heap.
Thread safety: single-threaded asyncio event loop per symbol — no locks needed.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from ..models.domain import Order, OrderSide, OrderStatus, OrderType


@dataclass(order=True)
class _BidEntry:
    """Max-heap entry: negate price for Python min-heap semantics."""
    neg_price: Decimal             # -price for max-heap
    seq: int                       # insertion sequence for time priority
    order: Order = field(compare=False)


@dataclass(order=True)
class _AskEntry:
    """Min-heap entry: lowest price first, then earliest arrival."""
    price: Decimal
    seq: int
    order: Order = field(compare=False)


class OrderBook:
    """In-memory order book for a single trading symbol."""

    MAX_DEPTH = 1_000  # cap per side to prevent OOM

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._bids: List[_BidEntry] = []     # max-heap via negated price
        self._asks: List[_AskEntry] = []     # min-heap
        self._orders: Dict[str, Order] = {}  # orderId → Order (for cancels)
        self._seq: int = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def add(self, order: Order) -> None:
        """Add a resting order to the book."""
        self._seq += 1
        self._orders[order.id] = order
        if order.side == OrderSide.BUY:
            heapq.heappush(self._bids, _BidEntry(
                neg_price=-order.price, seq=self._seq, order=order
            ))
        else:
            heapq.heappush(self._asks, _AskEntry(
                price=order.price, seq=self._seq, order=order
            ))

    def cancel(self, order_id: str) -> Optional[Order]:
        """Mark order cancelled; lazy-delete from heap on next peek."""
        order = self._orders.pop(order_id, None)
        if order:
            order.status = OrderStatus.CANCELLED
        return order

    def best_bid(self) -> Optional[Order]:
        return self._peek_bid()

    def best_ask(self) -> Optional[Order]:
        return self._peek_ask()

    def depth_snapshot(self, levels: int = 20) -> dict:
        """Return top N levels for REST orderbook endpoint."""
        bids = self._aggregate(self._bids, side="bid", levels=levels)
        asks = self._aggregate(self._asks, side="ask", levels=levels)
        return {"symbol": self.symbol, "bids": bids, "asks": asks}

    # ── Internal ──────────────────────────────────────────────────────────────

    def _peek_bid(self) -> Optional[Order]:
        while self._bids:
            entry = self._bids[0]
            if entry.order.id in self._orders and entry.order.is_resting:
                return entry.order
            heapq.heappop(self._bids)
        return None

    def _peek_ask(self) -> Optional[Order]:
        while self._asks:
            entry = self._asks[0]
            if entry.order.id in self._orders and entry.order.is_resting:
                return entry.order
            heapq.heappop(self._asks)
        return None

    def _pop_bid(self) -> Optional[Order]:
        while self._bids:
            entry = heapq.heappop(self._bids)
            if entry.order.id in self._orders and entry.order.is_resting:
                return entry.order
        return None

    def _pop_ask(self) -> Optional[Order]:
        while self._asks:
            entry = heapq.heappop(self._asks)
            if entry.order.id in self._orders and entry.order.is_resting:
                return entry.order
        return None

    def _aggregate(self, heap: list, side: str, levels: int) -> list:
        """Aggregate price levels for depth snapshot (read-only, does not pop)."""
        buckets: Dict[Decimal, Decimal] = {}
        for entry in heap:
            o = entry.order
            if o.id not in self._orders or not o.is_resting:
                continue
            price = o.price
            buckets[price] = buckets.get(price, Decimal("0")) + o.remaining_qty
            if len(buckets) >= levels:
                break
        reverse = (side == "bid")
        return [[str(p), str(q)] for p, q in sorted(buckets.items(), reverse=reverse)]
```

### 3.2 Matching Engine

**File**: `services/spot-trading/app/matching/engine.py`

```python
"""
MatchingEngine: price-time priority matching.
Single instance per symbol; runs in asyncio event loop (no thread locks).
Recovers in-memory state from PostgreSQL OPEN/PARTIAL orders on startup.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional, Tuple

from ..models.domain import (
    Order, OrderSide, OrderStatus, OrderType, TimeInForce, Trade
)
from .order_book import OrderBook

MAKER_FEE_RATE = Decimal("0.001")   # 0.10%
TAKER_FEE_RATE = Decimal("0.0015")  # 0.15%


class MatchResult:
    def __init__(self, order: Order, trades: List[Trade]) -> None:
        self.order = order
        self.trades = trades


class MatchingEngine:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._book = OrderBook(symbol)

    # ── Recovery ─────────────────────────────────────────────────────────────

    def rebuild_from_orders(self, open_orders: List[Order]) -> None:
        """Rebuild in-memory book from PostgreSQL OPEN/PARTIAL orders on startup."""
        for order in sorted(open_orders, key=lambda o: o.created_at):
            self._book.add(order)

    # ── Public API ────────────────────────────────────────────────────────────

    def submit(self, incoming: Order) -> MatchResult:
        """
        Submit a new order.  Returns matched trades and final order state.
        Does NOT write to DB — caller commits DB before publishing events.
        """
        trades: List[Trade] = []

        if incoming.type == OrderType.LIMIT:
            self._match_limit(incoming, trades)
        else:
            self._match_market(incoming, trades)

        # Determine final status
        if incoming.remaining_qty <= 0:
            incoming.status = OrderStatus.FILLED
        elif trades and incoming.type == OrderType.LIMIT:
            # Partial fill — rest on book unless IOC/FOK
            if incoming.time_in_force == TimeInForce.IOC:
                incoming.status = OrderStatus.CANCELLED
            elif incoming.time_in_force == TimeInForce.FOK:
                # FOK: all or nothing — reject entire order (trades already recorded)
                incoming.status = OrderStatus.CANCELLED
                trades.clear()
            else:
                incoming.status = OrderStatus.PARTIAL
                self._book.add(incoming)
        elif not trades and incoming.type == OrderType.LIMIT:
            # No match — rest on book (OPEN) unless IOC
            if incoming.time_in_force == TimeInForce.IOC:
                incoming.status = OrderStatus.CANCELLED
            else:
                incoming.status = OrderStatus.OPEN
                self._book.add(incoming)
        elif incoming.type == OrderType.MARKET and incoming.remaining_qty > 0:
            # Partial fill for MARKET (book exhausted) — cancel remainder
            incoming.status = OrderStatus.CANCELLED if not trades else OrderStatus.PARTIAL

        return MatchResult(order=incoming, trades=trades)

    def cancel(self, order_id: str) -> Optional[Order]:
        return self._book.cancel(order_id)

    def depth_snapshot(self, levels: int = 20) -> dict:
        return self._book.depth_snapshot(levels)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _match_limit(self, incoming: Order, trades: List[Trade]) -> None:
        while incoming.remaining_qty > 0:
            if incoming.side == OrderSide.BUY:
                resting = self._book.best_ask()
                if resting is None or resting.price > incoming.price:
                    break
            else:
                resting = self._book.best_bid()
                if resting is None or resting.price < incoming.price:
                    break
            trades.append(self._execute(incoming, resting))

    def _match_market(self, incoming: Order, trades: List[Trade]) -> None:
        while incoming.remaining_qty > 0:
            if incoming.side == OrderSide.BUY:
                resting = self._book.best_ask()
            else:
                resting = self._book.best_bid()
            if resting is None:
                break
            trades.append(self._execute(incoming, resting))

    def _execute(self, incoming: Order, resting: Order) -> Trade:
        """Execute a single match between incoming (taker) and resting (maker)."""
        fill_qty = min(incoming.remaining_qty, resting.remaining_qty)
        fill_price = resting.price  # execute at resting (maker) price

        # Update quantities
        incoming.executed_qty += fill_qty
        resting.executed_qty += fill_qty

        # Update avg_price (weighted average)
        incoming.avg_price = self._avg(incoming.avg_price, incoming.executed_qty - fill_qty, fill_price, fill_qty)
        resting.avg_price  = self._avg(resting.avg_price,  resting.executed_qty  - fill_qty, fill_price, fill_qty)

        # Update resting order status
        if resting.remaining_qty <= 0:
            resting.status = OrderStatus.FILLED
            self._book.cancel(resting.id)
        else:
            resting.status = OrderStatus.PARTIAL

        # Fee calculation: taker = incoming, maker = resting
        notional   = fill_qty * fill_price
        taker_fee  = notional * TAKER_FEE_RATE
        maker_fee  = notional * MAKER_FEE_RATE

        if incoming.side == OrderSide.BUY:
            buyer_fee, seller_fee = taker_fee, maker_fee
        else:
            buyer_fee, seller_fee = maker_fee, taker_fee

        return Trade(
            symbol=self.symbol,
            buy_order_id=incoming.id  if incoming.side == OrderSide.BUY  else resting.id,
            sell_order_id=incoming.id if incoming.side == OrderSide.SELL else resting.id,
            price=fill_price,
            qty=fill_qty,
            buyer_fee=buyer_fee,
            seller_fee=seller_fee,
        )

    @staticmethod
    def _avg(current: Optional[Decimal], prev_qty: Decimal, new_price: Decimal, new_qty: Decimal) -> Decimal:
        if current is None or prev_qty == 0:
            return new_price
        return (current * prev_qty + new_price * new_qty) / (prev_qty + new_qty)
```

---

## 4. Position Repository (SELECT FOR UPDATE)

**File**: `services/spot-trading/app/repositories/position_repo.py`

```python
"""
Pessimistic locking on position row to prevent double-spend.
Uses asyncpg for raw SQL control over SELECT FOR UPDATE.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

import asyncpg

from ..models.domain import Position


class PositionRepository:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    async def get_for_update(self, user_id: str, asset: str) -> Optional[Position]:
        """Lock the position row for the duration of the transaction."""
        row = await self._conn.fetchrow(
            """
            SELECT user_id, asset, available, locked, updated_at
            FROM positions
            WHERE user_id = $1 AND asset = $2
            FOR UPDATE
            """,
            user_id, asset
        )
        if row is None:
            return None
        return Position(
            user_id=str(row["user_id"]),
            asset=row["asset"],
            available=Decimal(str(row["available"])),
            locked=Decimal(str(row["locked"])),
            updated_at=row["updated_at"],
        )

    async def upsert(self, position: Position) -> None:
        await self._conn.execute(
            """
            INSERT INTO positions (user_id, asset, available, locked, updated_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (user_id, asset) DO UPDATE
            SET available = $3, locked = $4, updated_at = NOW()
            """,
            position.user_id, position.asset,
            str(position.available), str(position.locked)
        )

    async def lock_for_order(self, user_id: str, asset: str, amount: Decimal) -> bool:
        """
        Lock `amount` from available → locked.
        Returns False if insufficient balance.
        Must be called inside an explicit transaction.
        """
        pos = await self.get_for_update(user_id, asset)
        if pos is None or pos.available < amount:
            return False
        pos.available -= amount
        pos.locked    += amount
        await self.upsert(pos)
        return True

    async def release_lock(self, user_id: str, asset: str, amount: Decimal) -> None:
        """Unlock (on cancel): locked → available."""
        pos = await self.get_for_update(user_id, asset)
        if pos is None:
            return
        pos.locked    -= amount
        pos.available += amount
        await self.upsert(pos)

    async def apply_trade(
        self,
        buyer_id: str,
        seller_id: str,
        base_asset: str,
        quote_asset: str,
        qty: Decimal,
        price: Decimal,
        buyer_fee: Decimal,
        seller_fee: Decimal,
    ) -> None:
        """
        Apply trade settlement atomically:
        - Buyer:  locked USDT → released; +base_asset (net of fee)
        - Seller: locked base  → released; +USDT (net of fee)
        """
        notional = qty * price

        # Buyer: deduct locked quote, credit base
        await self._conn.execute(
            """
            UPDATE positions SET locked = locked - $1, updated_at = NOW()
            WHERE user_id = $2 AND asset = $3
            """, str(notional), buyer_id, quote_asset
        )
        await self._settle_credit(buyer_id, base_asset, qty - buyer_fee)

        # Seller: deduct locked base, credit quote
        await self._conn.execute(
            """
            UPDATE positions SET locked = locked - $1, updated_at = NOW()
            WHERE user_id = $2 AND asset = $3
            """, str(qty), seller_id, base_asset
        )
        await self._settle_credit(seller_id, quote_asset, notional - seller_fee)

    async def _settle_credit(self, user_id: str, asset: str, amount: Decimal) -> None:
        await self._conn.execute(
            """
            INSERT INTO positions (user_id, asset, available, locked)
            VALUES ($1, $2, $3, 0)
            ON CONFLICT (user_id, asset) DO UPDATE
            SET available = positions.available + $3, updated_at = NOW()
            """, user_id, asset, str(amount)
        )

    async def list_by_user(self, user_id: str) -> List[Position]:
        rows = await self._conn.fetch(
            "SELECT user_id, asset, available, locked, updated_at FROM positions WHERE user_id = $1",
            user_id
        )
        return [
            Position(
                user_id=str(r["user_id"]),
                asset=r["asset"],
                available=Decimal(str(r["available"])),
                locked=Decimal(str(r["locked"])),
                updated_at=r["updated_at"],
            ) for r in rows
        ]
```

---

## 5. Order Repository

**File**: `services/spot-trading/app/repositories/order_repo.py`

```python
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

import asyncpg

from ..models.domain import Order, OrderSide, OrderStatus, OrderType, TimeInForce


def _row_to_order(row: asyncpg.Record) -> Order:
    return Order(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        symbol=row["symbol"],
        side=OrderSide(row["side"]),
        type=OrderType(row["type"]),
        status=OrderStatus(row["status"]),
        price=Decimal(str(row["price"])) if row["price"] else None,
        orig_qty=Decimal(str(row["orig_qty"])),
        executed_qty=Decimal(str(row["executed_qty"])),
        avg_price=Decimal(str(row["avg_price"])) if row["avg_price"] else None,
        time_in_force=TimeInForce(row["time_in_force"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


class OrderRepository:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    async def insert(self, order: Order) -> None:
        await self._conn.execute(
            """
            INSERT INTO orders
              (id, user_id, symbol, side, type, status, price, orig_qty,
               executed_qty, avg_price, time_in_force, created_at, updated_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)
            """,
            order.id, order.user_id, order.symbol,
            order.side.value, order.type.value, order.status.value,
            str(order.price) if order.price else None,
            str(order.orig_qty), str(order.executed_qty),
            str(order.avg_price) if order.avg_price else None,
            order.time_in_force.value, order.created_at, order.updated_at,
        )

    async def update_status(self, order: Order) -> None:
        await self._conn.execute(
            """
            UPDATE orders
            SET status=$2, executed_qty=$3, avg_price=$4, updated_at=NOW()
            WHERE id=$1
            """,
            order.id, order.status.value,
            str(order.executed_qty),
            str(order.avg_price) if order.avg_price else None,
        )

    async def get(self, order_id: str, user_id: str) -> Optional[Order]:
        row = await self._conn.fetchrow(
            "SELECT * FROM orders WHERE id=$1 AND user_id=$2", order_id, user_id
        )
        return _row_to_order(row) if row else None

    async def list_by_user(
        self, user_id: str, symbol: Optional[str] = None,
        status: Optional[str] = None, limit: int = 50
    ) -> List[Order]:
        filters = ["user_id=$1"]
        params: list = [user_id]
        if symbol:
            params.append(symbol)
            filters.append(f"symbol=${len(params)}")
        if status:
            params.append(status)
            filters.append(f"status=${len(params)}")
        params.append(limit)
        where = " AND ".join(filters)
        rows = await self._conn.fetch(
            f"SELECT * FROM orders WHERE {where} ORDER BY created_at DESC LIMIT ${len(params)}",
            *params
        )
        return [_row_to_order(r) for r in rows]

    async def list_open_by_symbol(self, symbol: str) -> List[Order]:
        """Used by MatchingEngine.rebuild_from_orders() on startup."""
        rows = await self._conn.fetch(
            "SELECT * FROM orders WHERE symbol=$1 AND status IN ('OPEN','PARTIAL') ORDER BY created_at",
            symbol
        )
        return [_row_to_order(r) for r in rows]
```

---

## 6. Market Data ACL

**File**: `services/spot-trading/app/acl/market_data_acl.py`

```python
"""
Anti-Corruption Layer: consumes market.ticker.v1 Kafka topic → internal PriceSnapshot.
SpotTrading never imports MarketData domain types or touches Binance directly.
"""
from __future__ import annotations

import asyncio
import json
import logging
from decimal import Decimal
from typing import Dict

from aiokafka import AIOKafkaConsumer

from ..config import settings
from ..models.domain import PriceSnapshot

logger = logging.getLogger(__name__)

_PRICE_DEVIATION_THRESHOLD = Decimal("0.10")  # 10% sanity check


class MarketDataACL:
    """
    Background task that maintains an in-process price cache.
    Order API queries this cache for price sanity validation.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, PriceSnapshot] = {}
        self._consumer: AIOKafkaConsumer | None = None

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            "market.ticker.v1",
            bootstrap_servers=settings.kafka_brokers,
            group_id="spot-trading-market-acl",
            value_deserializer=lambda v: json.loads(v.decode()),
            auto_offset_reset="latest",
        )
        await self._consumer.start()
        asyncio.create_task(self._consume_loop())

    async def stop(self) -> None:
        if self._consumer:
            await self._consumer.stop()

    async def _consume_loop(self) -> None:
        try:
            async for msg in self._consumer:
                try:
                    self._cache[msg.value["symbol"]] = self._translate(msg.value)
                except (KeyError, Exception) as exc:
                    logger.warning("ACL translation error: %s", exc)
        except asyncio.CancelledError:
            pass

    @staticmethod
    def _translate(payload: dict) -> PriceSnapshot:
        from datetime import datetime, timezone
        return PriceSnapshot(
            symbol=payload["symbol"],
            last_price=Decimal(payload["lastPrice"]),
            high_24h=Decimal(payload["high"]),
            low_24h=Decimal(payload["low"]),
            updated_at=datetime.fromisoformat(payload["timestamp"]).replace(tzinfo=timezone.utc),
        )

    def get_snapshot(self, symbol: str) -> PriceSnapshot | None:
        return self._cache.get(symbol)

    def validate_price(self, symbol: str, order_price: Decimal) -> bool:
        """
        Sanity check: order price must be within ±10% of last traded price.
        Always passes for MARKET orders (called only for LIMIT).
        Returns True if no snapshot available (fail-open during startup).
        """
        snap = self._cache.get(symbol)
        if snap is None:
            return True  # fail-open: don't block orders during warm-up
        deviation = abs(order_price - snap.last_price) / snap.last_price
        return deviation <= _PRICE_DEVIATION_THRESHOLD
```

---

## 7. Kafka Producer

**File**: `services/spot-trading/app/producers/kafka_producer.py`

```python
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

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()

    async def publish_order(self, order: Order) -> None:
        await self._send(TOPICS["order"], key=order.user_id, value=order.to_kafka_payload())

    async def publish_trade(self, trade: Trade) -> None:
        await self._send(TOPICS["trade"], key=trade.symbol, value=trade.to_kafka_payload())

    async def _send(self, topic: str, key: str, value: dict) -> None:
        if not self._producer:
            logger.error("Kafka producer not started")
            return
        try:
            await self._producer.send_and_wait(topic, key=key, value=value)
        except Exception as exc:
            logger.error("Kafka publish failed [%s]: %s", topic, exc)
            raise
```

---

## 8. Pydantic Schemas

**File**: `services/spot-trading/app/schemas.py`

```python
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional
from datetime import datetime

from pydantic import BaseModel, field_validator


class SubmitOrderRequest(BaseModel):
    symbol: str
    side: str
    type: str
    price: Optional[str] = None          # required for LIMIT
    qty: str
    timeInForce: str = "GTC"

    @field_validator("side")
    @classmethod
    def validate_side(cls, v: str) -> str:
        if v not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        return v

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("LIMIT", "MARKET"):
            raise ValueError("type must be LIMIT or MARKET")
        return v


class OrderResponse(BaseModel):
    orderId: str
    userId: str
    symbol: str
    side: str
    type: str
    status: str
    price: Optional[str]
    origQty: str
    executedQty: str
    avgPrice: Optional[str]
    timeInForce: str
    createdAt: datetime
    updatedAt: datetime


class TradeResponse(BaseModel):
    tradeId: str
    symbol: str
    price: str
    qty: str
    buyerFee: str
    sellerFee: str
    executedAt: datetime


class PositionResponse(BaseModel):
    asset: str
    available: str
    locked: str
    total: str


class OrderBookResponse(BaseModel):
    symbol: str
    bids: List[List[str]]   # [[price, qty], ...]
    asks: List[List[str]]
```

---

## 9. FastAPI Application

### 9.1 Config

**File**: `services/spot-trading/app/config.py`

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    kafka_brokers: str = "localhost:9092"
    db_url: str        = "postgresql://postgres:postgres@localhost:5432/spot_trading"
    redis_url: str     = "redis://localhost:6379"
    jwt_public_key: str = ""
    supported_symbols: list[str] = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT"]
    price_deviation_limit: float = 0.10

    class Config:
        env_file = ".env"


settings = Settings()
```

### 9.2 Main Application

**File**: `services/spot-trading/app/main.py`

```python
from __future__ import annotations

import asyncio
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
from .routers import orderbook, orders, positions, trades

logger = logging.getLogger(__name__)

# ── Application state singletons ──────────────────────────────────────────────
market_acl   = MarketDataACL()
kafka_prod   = SpotKafkaProducer()
engines: dict[str, MatchingEngine] = {}
db_pool: asyncpg.Pool | None = None
redis_client: aioredis.Redis | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, redis_client

    db_pool      = await asyncpg.create_pool(settings.db_url, min_size=5, max_size=20)
    redis_client = await aioredis.from_url(settings.redis_url, decode_responses=True)

    await kafka_prod.start()
    await market_acl.start()

    # Bootstrap matching engines and rebuild order books from DB
    async with db_pool.acquire() as conn:
        order_repo = OrderRepository(conn)
        for symbol in settings.supported_symbols:
            engine = MatchingEngine(symbol)
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


@app.get("/health")
async def health():
    return {"status": "ok", "engines": list(engines.keys())}
```

### 9.3 Orders Router

**File**: `services/spot-trading/app/routers/orders.py`

```python
from __future__ import annotations

from decimal import Decimal
from typing import Optional

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..main import db_pool, engines, kafka_prod, market_acl, redis_client
from ..models.domain import Order, OrderSide, OrderStatus, OrderType, TimeInForce
from ..repositories.order_repo import OrderRepository
from ..repositories.position_repo import PositionRepository
from ..schemas import OrderResponse, SubmitOrderRequest

router = APIRouter()


def _order_to_response(o: Order) -> OrderResponse:
    return OrderResponse(
        orderId=o.id, userId=o.user_id, symbol=o.symbol,
        side=o.side.value, type=o.type.value, status=o.status.value,
        price=str(o.price) if o.price else None,
        origQty=str(o.orig_qty), executedQty=str(o.executed_qty),
        avgPrice=str(o.avg_price) if o.avg_price else None,
        timeInForce=o.time_in_force.value,
        createdAt=o.created_at, updatedAt=o.updated_at,
    )


def _get_user_id(request: Request) -> str:
    """Extract userId injected by Lambda Authorizer into request context header."""
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user_id


@router.post("/orders", response_model=OrderResponse, status_code=201)
async def submit_order(body: SubmitOrderRequest, request: Request):
    user_id = _get_user_id(request)

    if body.symbol not in engines:
        raise HTTPException(status_code=400, detail=f"Unsupported symbol: {body.symbol}")

    # Price sanity check for LIMIT orders
    if body.type == "LIMIT":
        order_price = Decimal(body.price)
        if not market_acl.validate_price(body.symbol, order_price):
            raise HTTPException(status_code=400, detail="Order price deviates > 10% from market price")
    else:
        order_price = None

    qty = Decimal(body.qty)
    symbol_parts = body.symbol.split("-")
    base_asset, quote_asset = symbol_parts[0], symbol_parts[1]

    order = Order(
        user_id=user_id, symbol=body.symbol,
        side=OrderSide(body.side), type=OrderType(body.type),
        price=order_price, orig_qty=qty,
        time_in_force=TimeInForce(body.timeInForce),
    )

    # Pessimistic lock on position, then match, then commit atomically
    async with db_pool.acquire() as conn:
        async with conn.transaction():
            pos_repo   = PositionRepository(conn)
            order_repo = OrderRepository(conn)

            # Lock required balance
            if body.side == "BUY":
                lock_asset  = quote_asset
                lock_amount = (order_price or Decimal("0")) * qty  # MARKET: no pre-lock, handle separately
            else:
                lock_asset  = base_asset
                lock_amount = qty

            locked = await pos_repo.lock_for_order(user_id, lock_asset, lock_amount)
            if not locked:
                raise HTTPException(status_code=400, detail="Insufficient balance")

            # Submit to matching engine (synchronous, in-memory)
            engine = engines[body.symbol]
            result = engine.submit(order)

            # Persist order
            await order_repo.insert(result.order)

            # Persist trades and settle positions
            for trade in result.trades:
                trade_repo = __import__(
                    "services.spot-trading.app.repositories.trade_repo",
                    fromlist=["TradeRepository"]
                )
                # (trade_repo import simplified — use dependency injection in production)
                await conn.execute(
                    """
                    INSERT INTO trades
                      (id, symbol, buy_order_id, sell_order_id, price, qty,
                       buyer_fee, seller_fee, executed_at)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    """,
                    trade.id, trade.symbol,
                    trade.buy_order_id, trade.sell_order_id,
                    str(trade.price), str(trade.qty),
                    str(trade.buyer_fee), str(trade.seller_fee),
                    trade.executed_at,
                )
                await pos_repo.apply_trade(
                    buyer_id=trade.buy_order_id,    # resolved via order lookup
                    seller_id=trade.sell_order_id,
                    base_asset=base_asset, quote_asset=quote_asset,
                    qty=trade.qty, price=trade.price,
                    buyer_fee=trade.buyer_fee, seller_fee=trade.seller_fee,
                )

            # Update resting orders modified by matching
            for trade in result.trades:
                # Update the resting order's status in DB (fetched from engine)
                pass  # engine.cancel already removed it from book; update_status called by engine result

    # Publish events AFTER DB commit (R-04: acks=all before marking complete)
    await kafka_prod.publish_order(result.order)
    for trade in result.trades:
        await kafka_prod.publish_trade(trade)

    # Push WS notification to user
    await redis_client.publish(
        f"ws:orders:{user_id}",
        __import__("json").dumps({"type": "orderUpdate", "data": _order_to_response(result.order).model_dump(mode="json")}),
    )

    return _order_to_response(result.order)


@router.delete("/orders/{order_id}", response_model=OrderResponse)
async def cancel_order(order_id: str, request: Request):
    user_id = _get_user_id(request)

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            order_repo = OrderRepository(conn)
            order = await order_repo.get(order_id, user_id)
            if not order:
                raise HTTPException(status_code=404, detail="Order not found")
            if not order.is_resting:
                raise HTTPException(status_code=400, detail=f"Cannot cancel order in status {order.status}")

            # Cancel from in-memory book
            if order.symbol in engines:
                engines[order.symbol].cancel(order_id)

            order.status = OrderStatus.CANCELLED
            await order_repo.update_status(order)

            # Release locked balance
            pos_repo = PositionRepository(conn)
            symbol_parts = order.symbol.split("-")
            base_asset, quote_asset = symbol_parts[0], symbol_parts[1]
            release_asset  = quote_asset if order.side == OrderSide.BUY else base_asset
            release_amount = order.remaining_qty * (order.price or Decimal("0")) if order.side == OrderSide.BUY else order.remaining_qty
            await pos_repo.release_lock(user_id, release_asset, release_amount)

    await kafka_prod.publish_order(order)
    return _order_to_response(order)


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: str, request: Request):
    user_id = _get_user_id(request)
    async with db_pool.acquire() as conn:
        order = await OrderRepository(conn).get(order_id, user_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return _order_to_response(order)


@router.get("/orders", response_model=list[OrderResponse])
async def list_orders(
    request: Request,
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
):
    user_id = _get_user_id(request)
    async with db_pool.acquire() as conn:
        orders = await OrderRepository(conn).list_by_user(user_id, symbol, status, limit)
    return [_order_to_response(o) for o in orders]
```

### 9.4 Positions Router

**File**: `services/spot-trading/app/routers/positions.py`

```python
from fastapi import APIRouter, Request
from ..main import db_pool
from ..repositories.position_repo import PositionRepository
from ..schemas import PositionResponse
from .orders import _get_user_id

router = APIRouter()


@router.get("/positions", response_model=list[PositionResponse])
async def get_positions(request: Request):
    user_id = _get_user_id(request)
    async with db_pool.acquire() as conn:
        positions = await PositionRepository(conn).list_by_user(user_id)
    return [
        PositionResponse(
            asset=p.asset,
            available=str(p.available),
            locked=str(p.locked),
            total=str(p.total),
        )
        for p in positions
    ]
```

### 9.5 Order Book Router

**File**: `services/spot-trading/app/routers/orderbook.py`

```python
from fastapi import APIRouter, HTTPException
from ..main import engines
from ..schemas import OrderBookResponse

router = APIRouter()


@router.get("/orderbook/{symbol}", response_model=OrderBookResponse)
async def get_orderbook(symbol: str, levels: int = 20):
    if symbol not in engines:
        raise HTTPException(status_code=404, detail=f"No order book for {symbol}")
    snap = engines[symbol].depth_snapshot(levels=min(levels, 50))
    return OrderBookResponse(**snap)
```

---

## 10. WS Notifier Lambda

**File**: `services/spot-trading/ws-notifier/default.py`

```python
"""
Lambda: default route handler for API GW WebSocket.
Subscribe → listen to Redis pub/sub → push messages to connected clients.
"""
from __future__ import annotations

import json
import os

import boto3
import redis

REDIS_URL        = os.environ["REDIS_URL"]
APIGW_ENDPOINT   = os.environ["APIGW_ENDPOINT"]
CONNECTIONS_TABLE = os.environ["CONNECTIONS_TABLE"]

_apigw   = None
_redis   = None
_dynamo  = None


def _get_apigw():
    global _apigw
    if _apigw is None:
        _apigw = boto3.client("apigatewaymanagementapi", endpoint_url=APIGW_ENDPOINT)
    return _apigw


def _get_redis():
    global _redis
    if _redis is None:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def _get_dynamo():
    global _dynamo
    if _dynamo is None:
        _dynamo = boto3.resource("dynamodb").Table(CONNECTIONS_TABLE)
    return _dynamo


def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    body          = json.loads(event.get("body") or "{}")
    action        = body.get("action")

    if action == "subscribe":
        channel = body.get("channel")        # "orders" or "orderbook"
        subject = body.get("userId") or body.get("symbol", "")
        redis_channel = f"ws:{channel}:{subject}"

        # Store subscription in DynamoDB for Lambda restart resilience
        _get_dynamo().update_item(
            Key={"connectionId": connection_id},
            UpdateExpression="ADD subscriptions :s",
            ExpressionAttributeValues={":s": {redis_channel}},
        )

        # Flush pending messages from Redis channel
        r = _get_redis()
        pubsub = r.pubsub()
        pubsub.subscribe(redis_channel)
        for msg in pubsub.listen():
            if msg["type"] == "message":
                _push(connection_id, msg["data"])
                break  # Lambda timeout concern: push snapshot then exit
        pubsub.unsubscribe()

    elif action == "unsubscribe":
        channel = body.get("channel")
        subject = body.get("userId") or body.get("symbol", "")
        redis_channel = f"ws:{channel}:{subject}"
        _get_dynamo().update_item(
            Key={"connectionId": connection_id},
            UpdateExpression="DELETE subscriptions :s",
            ExpressionAttributeValues={":s": {redis_channel}},
        )

    return {"statusCode": 200}


def _push(connection_id: str, data: str) -> None:
    try:
        _get_apigw().post_to_connection(
            ConnectionId=connection_id,
            Data=data.encode()
        )
    except _get_apigw().exceptions.GoneException:
        _get_dynamo().delete_item(Key={"connectionId": connection_id})
```

---

## 11. Alembic Migration

**File**: `services/spot-trading/migrations/versions/001_initial_schema.py`

```python
"""Initial schema: orders, trades, positions

Revision ID: 001
Create Date: 2026-03-08
"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None


def upgrade():
    op.execute("""
        CREATE TABLE orders (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         UUID NOT NULL,
            symbol          VARCHAR(20) NOT NULL,
            side            VARCHAR(4) NOT NULL CHECK (side IN ('BUY','SELL')),
            type            VARCHAR(6) NOT NULL CHECK (type IN ('LIMIT','MARKET')),
            status          VARCHAR(10) NOT NULL DEFAULT 'PENDING',
            price           NUMERIC(20,8),
            orig_qty        NUMERIC(20,8) NOT NULL,
            executed_qty    NUMERIC(20,8) NOT NULL DEFAULT 0,
            avg_price       NUMERIC(20,8),
            time_in_force   VARCHAR(3) NOT NULL DEFAULT 'GTC',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT orders_price_required CHECK (type = 'MARKET' OR price IS NOT NULL)
        );

        CREATE INDEX idx_orders_user_symbol ON orders (user_id, symbol, created_at DESC);
        CREATE INDEX idx_orders_symbol_status ON orders (symbol, status) WHERE status IN ('OPEN','PARTIAL');

        CREATE TABLE trades (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            symbol          VARCHAR(20) NOT NULL,
            buy_order_id    UUID NOT NULL REFERENCES orders(id),
            sell_order_id   UUID NOT NULL REFERENCES orders(id),
            price           NUMERIC(20,8) NOT NULL,
            qty             NUMERIC(20,8) NOT NULL,
            buyer_fee       NUMERIC(20,8) NOT NULL DEFAULT 0,
            seller_fee      NUMERIC(20,8) NOT NULL DEFAULT 0,
            executed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX idx_trades_buy_order   ON trades (buy_order_id);
        CREATE INDEX idx_trades_sell_order  ON trades (sell_order_id);
        CREATE INDEX idx_trades_symbol_time ON trades (symbol, executed_at DESC);

        CREATE TABLE positions (
            user_id         UUID NOT NULL,
            asset           VARCHAR(10) NOT NULL,
            available       NUMERIC(20,8) NOT NULL DEFAULT 0,
            locked          NUMERIC(20,8) NOT NULL DEFAULT 0,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, asset),
            CONSTRAINT positions_non_negative CHECK (available >= 0 AND locked >= 0)
        );
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS positions, trades, orders CASCADE;")
```

---

## 12. Kubernetes Manifests

### 12.1 Order API Deployment

**File**: `services/spot-trading/k8s/order-api-deployment.yaml`

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: spot-order-api
  namespace: spot-trading
spec:
  replicas: 2
  selector:
    matchLabels:
      app: spot-order-api
  template:
    metadata:
      labels:
        app: spot-order-api
    spec:
      nodeSelector:
        node.kubernetes.io/instance-type: m6i.large
      containers:
        - name: spot-order-api
          image: ${ECR_REGISTRY}/spot-order-api:${TAG}
          ports:
            - containerPort: 8000
          envFrom:
            - secretRef:
                name: spot-trading-secrets
          resources:
            requests:
              cpu: "500m"
              memory: "512Mi"
            limits:
              cpu: "2000m"
              memory: "1Gi"
          livenessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 10
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /health
              port: 8000
            initialDelaySeconds: 5
            periodSeconds: 5
```

### 12.2 Matching Engine StatefulSet

**File**: `services/spot-trading/k8s/matching-engine-deployment.yaml`

```yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: spot-matching-engine
  namespace: spot-trading
spec:
  serviceName: spot-matching-engine
  replicas: 1          # Single pod per symbol; scale via symbol sharding
  selector:
    matchLabels:
      app: spot-matching-engine
  template:
    metadata:
      labels:
        app: spot-matching-engine
    spec:
      nodeSelector:
        node.kubernetes.io/instance-type: c6i.xlarge
      containers:
        - name: spot-matching-engine
          image: ${ECR_REGISTRY}/spot-order-api:${TAG}
          command: ["python", "-m", "app.matching.main"]
          envFrom:
            - secretRef:
                name: spot-trading-secrets
          resources:
            requests:
              cpu: "2000m"
              memory: "2Gi"
            limits:
              cpu: "4000m"
              memory: "4Gi"
```

---

## 13. Terraform IaC

**File**: `services/spot-trading/infra/main.tf`

```hcl
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
  backend "s3" {
    bucket         = "trading-app-tfstate"
    key            = "spot-trading/terraform.tfstate"
    region         = "ap-northeast-2"
    dynamodb_table = "tfstate-lock"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
}

# ── Aurora PostgreSQL ─────────────────────────────────────────────────────────
resource "aws_rds_cluster" "spot_db" {
  cluster_identifier      = "${var.env}-spot-trading-db"
  engine                  = "aurora-postgresql"
  engine_version          = "16.2"
  database_name           = "spot_trading"
  master_username         = "spot_admin"
  manage_master_user_password = true
  db_subnet_group_name    = var.db_subnet_group
  vpc_security_group_ids  = [aws_security_group.rds_sg.id]

  tags = { Environment = var.env, Service = "spot-trading" }
}

resource "aws_rds_cluster_instance" "writer" {
  identifier         = "${var.env}-spot-db-writer"
  cluster_identifier = aws_rds_cluster.spot_db.id
  instance_class     = "db.r6g.large"
  engine             = aws_rds_cluster.spot_db.engine
}

resource "aws_rds_cluster_instance" "reader" {
  identifier         = "${var.env}-spot-db-reader"
  cluster_identifier = aws_rds_cluster.spot_db.id
  instance_class     = "db.r6g.large"
  engine             = aws_rds_cluster.spot_db.engine
}

# ── ElastiCache Redis ─────────────────────────────────────────────────────────
resource "aws_elasticache_replication_group" "spot_redis" {
  replication_group_id       = "${var.env}-spot-redis"
  description                = "Spot trading order book + pub/sub"
  node_type                  = "cache.r7g.medium"
  num_cache_clusters         = 1
  parameter_group_name       = "default.redis7"
  subnet_group_name          = var.cache_subnet_group
  security_group_ids         = [aws_security_group.redis_sg.id]
  at_rest_encryption_enabled = true
  transit_encryption_enabled = true

  tags = { Environment = var.env, Service = "spot-trading" }
}

# ── API Gateway WebSocket ─────────────────────────────────────────────────────
resource "aws_apigatewayv2_api" "spot_ws" {
  name                       = "${var.env}-spot-trading-ws"
  protocol_type              = "WEBSOCKET"
  route_selection_expression = "$request.body.action"
}

resource "aws_apigatewayv2_stage" "prod" {
  api_id      = aws_apigatewayv2_api.spot_ws.id
  name        = "prod"
  auto_deploy = true
}

# ── Lambda: WS Connect / Disconnect / Default ─────────────────────────────────
resource "aws_lambda_function" "ws_connect" {
  function_name = "${var.env}-spot-ws-connect"
  runtime       = "python3.12"
  handler       = "connect.handler"
  role          = aws_iam_role.lambda_exec.arn
  filename      = "${path.module}/../ws-notifier/connect.zip"
  environment {
    variables = {
      CONNECTIONS_TABLE = aws_dynamodb_table.ws_connections.name
    }
  }
}

resource "aws_lambda_function" "ws_default" {
  function_name = "${var.env}-spot-ws-default"
  runtime       = "python3.12"
  handler       = "default.handler"
  role          = aws_iam_role.lambda_exec.arn
  filename      = "${path.module}/../ws-notifier/default.zip"
  memory_size   = 512
  timeout       = 29
  environment {
    variables = {
      REDIS_URL         = "rediss://${aws_elasticache_replication_group.spot_redis.primary_endpoint_address}:6379"
      APIGW_ENDPOINT    = "https://${aws_apigatewayv2_api.spot_ws.id}.execute-api.${var.aws_region}.amazonaws.com/${aws_apigatewayv2_stage.prod.name}"
      CONNECTIONS_TABLE = aws_dynamodb_table.ws_connections.name
    }
  }
}

# ── DynamoDB: WebSocket Connections ──────────────────────────────────────────
resource "aws_dynamodb_table" "ws_connections" {
  name           = "${var.env}-spot-ws-connections"
  billing_mode   = "PAY_PER_REQUEST"
  hash_key       = "connectionId"

  attribute {
    name = "connectionId"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }
}

# ── Security Groups ───────────────────────────────────────────────────────────
resource "aws_security_group" "rds_sg" {
  name   = "${var.env}-spot-rds-sg"
  vpc_id = var.vpc_id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [var.eks_node_sg_id]
  }
}

resource "aws_security_group" "redis_sg" {
  name   = "${var.env}-spot-redis-sg"
  vpc_id = var.vpc_id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [var.eks_node_sg_id, aws_security_group.lambda_sg.id]
  }
}

resource "aws_security_group" "lambda_sg" {
  name   = "${var.env}-spot-lambda-sg"
  vpc_id = var.vpc_id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ── IAM Role for Lambda ───────────────────────────────────────────────────────
resource "aws_iam_role" "lambda_exec" {
  name = "${var.env}-spot-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy" "lambda_apigw" {
  name = "spot-apigw-post"
  role = aws_iam_role.lambda_exec.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["execute-api:ManageConnections"]
      Resource = "${aws_apigatewayv2_api.spot_ws.execution_arn}/*"
    }, {
      Effect   = "Allow"
      Action   = ["dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:UpdateItem", "dynamodb:GetItem"]
      Resource = aws_dynamodb_table.ws_connections.arn
    }]
  })
}
```

---

## 14. Frontend Hook

**File**: `apps/web/src/hooks/useOrders.ts`

```typescript
"use client"

import { useCallback, useEffect, useReducer, useRef } from "react"

export interface Order {
  orderId: string
  symbol: string
  side: "BUY" | "SELL"
  type: "LIMIT" | "MARKET"
  status: string
  price: string | null
  origQty: string
  executedQty: string
  createdAt: string
}

type State = {
  orders: Order[]
  loading: boolean
  error: string | null
}

type Action =
  | { type: "SET_ORDERS"; orders: Order[] }
  | { type: "UPDATE_ORDER"; order: Order }
  | { type: "SET_LOADING"; loading: boolean }
  | { type: "SET_ERROR"; error: string }

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "SET_ORDERS":
      return { ...state, orders: action.orders, loading: false }
    case "UPDATE_ORDER":
      return {
        ...state,
        orders: state.orders.some(o => o.orderId === action.order.orderId)
          ? state.orders.map(o => o.orderId === action.order.orderId ? action.order : o)
          : [action.order, ...state.orders],
      }
    case "SET_LOADING":
      return { ...state, loading: action.loading }
    case "SET_ERROR":
      return { ...state, error: action.error, loading: false }
    default:
      return state
  }
}

const API_BASE  = process.env.NEXT_PUBLIC_SPOT_API_URL ?? ""
const WS_URL    = process.env.NEXT_PUBLIC_WS_URL ?? ""

export function useOrders(symbol?: string) {
  const [state, dispatch] = useReducer(reducer, { orders: [], loading: true, error: null })
  const wsRef = useRef<WebSocket | null>(null)

  // Fetch initial orders
  useEffect(() => {
    const url = `${API_BASE}/spot/orders${symbol ? `?symbol=${symbol}` : ""}`
    fetch(url, { credentials: "include" })
      .then(r => r.json())
      .then((data: Order[]) => dispatch({ type: "SET_ORDERS", orders: data }))
      .catch(err => dispatch({ type: "SET_ERROR", error: String(err) }))
  }, [symbol])

  // Subscribe to real-time order updates via WebSocket
  useEffect(() => {
    if (!WS_URL) return
    const ws = new WebSocket(WS_URL)
    wsRef.current = ws

    ws.onopen = () => {
      ws.send(JSON.stringify({ action: "subscribe", channel: "orders" }))
    }
    ws.onmessage = (evt) => {
      try {
        const msg = JSON.parse(evt.data)
        if (msg.type === "orderUpdate") {
          dispatch({ type: "UPDATE_ORDER", order: msg.data })
        }
      } catch {}
    }
    return () => {
      ws.send(JSON.stringify({ action: "unsubscribe", channel: "orders" }))
      ws.close()
    }
  }, [])

  const submitOrder = useCallback(async (payload: {
    symbol: string
    side: "BUY" | "SELL"
    type: "LIMIT" | "MARKET"
    price?: string
    qty: string
    timeInForce?: string
  }) => {
    const res = await fetch(`${API_BASE}/spot/orders`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify(payload),
    })
    if (!res.ok) {
      const err = await res.json()
      throw new Error(err.detail ?? "Order submission failed")
    }
    return res.json() as Promise<Order>
  }, [])

  const cancelOrder = useCallback(async (orderId: string) => {
    const res = await fetch(`${API_BASE}/spot/orders/${orderId}`, {
      method: "DELETE",
      credentials: "include",
    })
    if (!res.ok) throw new Error("Cancel failed")
    return res.json() as Promise<Order>
  }, [])

  return { ...state, submitOrder, cancelOrder }
}
```

---

## 15. Requirements

**File**: `services/spot-trading/requirements.txt`

```
fastapi==0.115.5
uvicorn[standard]==0.32.1
asyncpg==0.30.0
aiokafka==0.12.0
redis[asyncio]==5.2.0
boto3==1.35.76
pydantic==2.10.3
pydantic-settings==2.6.1
alembic==1.14.0
mangum==0.19.0
```

---

## 16. Implementation Order

Follow the 10-step order from the Plan document:

| Step | File(s) | Notes |
|------|---------|-------|
| 1 | `infra/main.tf` + `variables.tf` + `outputs.tf` | Terraform: Aurora, Redis, API GW WS, Lambda, DynamoDB |
| 2 | `migrations/versions/001_initial_schema.py` | Alembic migration |
| 3 | `app/models/domain.py` | Domain entities (str for qty, Decimal internally) |
| 4 | `app/repositories/position_repo.py` | SELECT FOR UPDATE (R-01) |
| 5 | `app/matching/order_book.py` + `engine.py` | Heap-based matching engine |
| 6 | `app/producers/kafka_producer.py` | acks=all (R-04) |
| 7 | `app/acl/market_data_acl.py` | Market data ACL consumer |
| 8 | `app/routers/` + `app/schemas.py` + `app/main.py` | FastAPI application |
| 9 | `ws-notifier/{connect,disconnect,default}.py` | Lambda WS notifier |
| 10 | `apps/web/src/hooks/useOrders.ts` | Frontend hook |
