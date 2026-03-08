"""
MatchingEngine: price-time priority matching.
Single instance per symbol; runs in asyncio event loop (no thread locks).
Recovers in-memory state from PostgreSQL OPEN/PARTIAL orders on startup (R-03).
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from ..models.domain import (
    Order, OrderSide, OrderStatus, OrderType, TimeInForce, Trade,
)
from .order_book import OrderBook

MAKER_FEE_RATE = Decimal("0.001")    # 0.10%
TAKER_FEE_RATE = Decimal("0.0015")   # 0.15%


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
        """Rebuild in-memory book from PostgreSQL OPEN/PARTIAL orders on startup (R-03)."""
        for order in sorted(open_orders, key=lambda o: o.created_at):
            self._book.add(order)

    # ── Public API ────────────────────────────────────────────────────────────

    def submit(self, incoming: Order) -> MatchResult:
        """
        Submit a new order. Returns matched trades and final order state.
        Does NOT write to DB — caller commits DB before publishing Kafka events (R-04).
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
            if incoming.time_in_force == TimeInForce.IOC:
                incoming.status = OrderStatus.CANCELLED
            elif incoming.time_in_force == TimeInForce.FOK:
                # FOK: all or nothing — cancel entire order, undo trades
                incoming.status = OrderStatus.CANCELLED
                trades.clear()
            else:
                incoming.status = OrderStatus.PARTIAL
                self._book.add(incoming)
        elif not trades and incoming.type == OrderType.LIMIT:
            if incoming.time_in_force == TimeInForce.IOC:
                incoming.status = OrderStatus.CANCELLED
            else:
                incoming.status = OrderStatus.OPEN
                self._book.add(incoming)
        elif incoming.type == OrderType.MARKET and incoming.remaining_qty > 0:
            # Book exhausted — cancel remainder
            incoming.status = OrderStatus.PARTIAL if trades else OrderStatus.CANCELLED

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
            resting = self._book.best_ask() if incoming.side == OrderSide.BUY else self._book.best_bid()
            if resting is None:
                break
            trades.append(self._execute(incoming, resting))

    def _execute(self, incoming: Order, resting: Order) -> Trade:
        """Execute a single match between incoming (taker) and resting (maker)."""
        fill_qty   = min(incoming.remaining_qty, resting.remaining_qty)
        fill_price = resting.price  # execute at resting (maker) price

        # Update quantities
        incoming.executed_qty += fill_qty
        resting.executed_qty  += fill_qty

        # Update weighted average prices
        incoming.avg_price = self._avg(
            incoming.avg_price, incoming.executed_qty - fill_qty, fill_price, fill_qty
        )
        resting.avg_price = self._avg(
            resting.avg_price, resting.executed_qty - fill_qty, fill_price, fill_qty
        )

        # Update resting order status
        if resting.remaining_qty <= 0:
            resting.status = OrderStatus.FILLED
            self._book.cancel(resting.id)
        else:
            resting.status = OrderStatus.PARTIAL

        # Fee: taker = incoming (aggressive), maker = resting
        notional  = fill_qty * fill_price
        taker_fee = notional * TAKER_FEE_RATE
        maker_fee = notional * MAKER_FEE_RATE

        if incoming.side == OrderSide.BUY:
            buy_order_id, sell_order_id = incoming.id, resting.id
            buyer_fee, seller_fee = taker_fee, maker_fee
        else:
            buy_order_id, sell_order_id = resting.id, incoming.id
            buyer_fee, seller_fee = maker_fee, taker_fee

        return Trade(
            symbol=self.symbol,
            buy_order_id=buy_order_id,
            sell_order_id=sell_order_id,
            price=fill_price,
            qty=fill_qty,
            buyer_fee=buyer_fee,
            seller_fee=seller_fee,
        )

    @staticmethod
    def _avg(
        current: Optional[Decimal],
        prev_qty: Decimal,
        new_price: Decimal,
        new_qty: Decimal,
    ) -> Decimal:
        if current is None or prev_qty == 0:
            return new_price
        return (current * prev_qty + new_price * new_qty) / (prev_qty + new_qty)
