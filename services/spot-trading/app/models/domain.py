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
    id: str                          = field(default_factory=_new_id)
    user_id: str                     = ""
    symbol: str                      = ""
    side: OrderSide                  = OrderSide.BUY
    type: OrderType                  = OrderType.LIMIT
    status: OrderStatus              = OrderStatus.PENDING
    price: Optional[Decimal]         = None    # None for MARKET orders
    orig_qty: Decimal                = Decimal("0")
    executed_qty: Decimal            = Decimal("0")
    avg_price: Optional[Decimal]     = None
    time_in_force: TimeInForce       = TimeInForce.GTC
    created_at: datetime             = field(default_factory=_now_utc)
    updated_at: datetime             = field(default_factory=_now_utc)

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
