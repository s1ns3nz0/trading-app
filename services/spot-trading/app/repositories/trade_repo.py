from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

import asyncpg

from ..models.domain import Trade


def _row_to_trade(row: asyncpg.Record) -> Trade:
    return Trade(
        id=str(row["id"]),
        symbol=row["symbol"],
        buy_order_id=str(row["buy_order_id"]),
        sell_order_id=str(row["sell_order_id"]),
        price=Decimal(str(row["price"])),
        qty=Decimal(str(row["qty"])),
        buyer_fee=Decimal(str(row["buyer_fee"])),
        seller_fee=Decimal(str(row["seller_fee"])),
        executed_at=row["executed_at"],
    )


class TradeRepository:
    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    async def insert(self, trade: Trade) -> None:
        await self._conn.execute(
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

    async def list_by_user(
        self,
        user_id: str,
        symbol: Optional[str] = None,
        limit: int = 50,
    ) -> List[Trade]:
        # Trades don't store userId directly; join via orders
        filters = ["(o_buy.user_id=$1 OR o_sell.user_id=$1)"]
        params: list = [user_id]
        if symbol:
            params.append(symbol)
            filters.append(f"t.symbol=${len(params)}")
        params.append(limit)
        where = " AND ".join(filters)
        rows = await self._conn.fetch(
            f"""
            SELECT t.*
            FROM trades t
            JOIN orders o_buy  ON t.buy_order_id  = o_buy.id
            JOIN orders o_sell ON t.sell_order_id = o_sell.id
            WHERE {where}
            ORDER BY t.executed_at DESC
            LIMIT ${len(params)}
            """,
            *params
        )
        return [_row_to_trade(r) for r in rows]
