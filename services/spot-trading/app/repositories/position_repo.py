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

        # Buyer: deduct locked quote, credit base (net of taker fee)
        await self._conn.execute(
            """
            UPDATE positions SET locked = locked - $1, updated_at = NOW()
            WHERE user_id = $2 AND asset = $3
            """,
            str(notional), buyer_id, quote_asset
        )
        await self._settle_credit(buyer_id, base_asset, qty - buyer_fee)

        # Seller: deduct locked base, credit quote (net of maker fee)
        await self._conn.execute(
            """
            UPDATE positions SET locked = locked - $1, updated_at = NOW()
            WHERE user_id = $2 AND asset = $3
            """,
            str(qty), seller_id, base_asset
        )
        await self._settle_credit(seller_id, quote_asset, notional - seller_fee)

    async def _settle_credit(self, user_id: str, asset: str, amount: Decimal) -> None:
        await self._conn.execute(
            """
            INSERT INTO positions (user_id, asset, available, locked)
            VALUES ($1, $2, $3, 0)
            ON CONFLICT (user_id, asset) DO UPDATE
            SET available = positions.available + $3, updated_at = NOW()
            """,
            user_id, asset, str(amount)
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
            )
            for r in rows
        ]
