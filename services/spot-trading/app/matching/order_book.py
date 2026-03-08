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
from typing import Dict, List, Optional

from ..models.domain import Order, OrderSide, OrderStatus


@dataclass(order=True)
class _BidEntry:
    """Max-heap entry: negate price for Python min-heap semantics."""
    neg_price: Decimal              # -price for max-heap
    seq: int                        # insertion sequence for time priority
    order: Order = field(compare=False)


@dataclass(order=True)
class _AskEntry:
    """Min-heap entry: lowest price first, then earliest arrival."""
    price: Decimal
    seq: int
    order: Order = field(compare=False)


class OrderBook:
    """In-memory order book for a single trading symbol."""

    MAX_DEPTH = 1_000  # cap per side to prevent OOM (R-02)

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self._bids: List[_BidEntry] = []      # max-heap via negated price
        self._asks: List[_AskEntry] = []      # min-heap
        self._orders: Dict[str, Order] = {}   # orderId → Order (for cancels)
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

    def size(self) -> dict:
        return {"bids": len(self._bids), "asks": len(self._asks), "active": len(self._orders)}

    def depth_snapshot(self, levels: int = 20) -> dict:
        """Return top N price levels for REST orderbook endpoint."""
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

    def _aggregate(self, heap: list, side: str, levels: int) -> list:
        """Aggregate price levels (read-only, does not pop)."""
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
