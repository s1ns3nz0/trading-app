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
            "SELECT * FROM orders WHERE id=$1 AND user_id=$2",
            order_id, user_id
        )
        return _row_to_order(row) if row else None

    async def list_by_user(
        self,
        user_id: str,
        symbol: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
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
        """Used by MatchingEngine.rebuild_from_orders() on startup (R-03)."""
        rows = await self._conn.fetch(
            "SELECT * FROM orders WHERE symbol=$1 AND status IN ('OPEN','PARTIAL') ORDER BY created_at",
            symbol
        )
        return [_row_to_order(r) for r in rows]
