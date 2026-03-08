from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import List, Optional

import asyncpg

from ..models.domain import DepositRequest, DepositStatus, DepositType


class DepositRepository(ABC):

    @abstractmethod
    async def create(self, deposit: DepositRequest) -> DepositRequest: ...

    @abstractmethod
    async def get(self, deposit_id: str) -> Optional[DepositRequest]: ...

    @abstractmethod
    async def get_by_tx_hash(self, tx_hash: str) -> Optional[DepositRequest]: ...

    @abstractmethod
    async def get_by_bank_reference(
        self, bank_reference: str
    ) -> Optional[DepositRequest]: ...

    @abstractmethod
    async def update_status(
        self,
        deposit_id: str,
        new_status: DepositStatus,
        note: str = "",
        **kwargs,
    ) -> None: ...

    @abstractmethod
    async def list_by_user(
        self, user_id: str, limit: int = 50
    ) -> List[DepositRequest]: ...

    @abstractmethod
    async def get_expired(self) -> List[DepositRequest]: ...


class PostgresDepositRepository(DepositRepository):
    def __init__(self, conn: asyncpg.Connection) -> None:
        self._conn = conn

    async def create(self, d: DepositRequest) -> DepositRequest:
        row = await self._conn.fetchrow(
            """
            INSERT INTO finance.deposits
              (id, user_id, type, asset, amount, wallet_address, bank_reference,
               required_confirmations, expires_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            RETURNING *
            """,
            d.id,
            d.user_id,
            d.type.value,
            d.asset,
            str(d.amount),
            d.wallet_address,
            d.bank_reference,
            d.required_confirmations,
            d.expires_at,
        )
        return _row_to_deposit(row)

    async def get(self, deposit_id: str) -> Optional[DepositRequest]:
        row = await self._conn.fetchrow(
            "SELECT * FROM finance.deposits WHERE id = $1", deposit_id
        )
        return _row_to_deposit(row) if row else None

    async def get_by_tx_hash(self, tx_hash: str) -> Optional[DepositRequest]:
        row = await self._conn.fetchrow(
            "SELECT * FROM finance.deposits WHERE tx_hash = $1", tx_hash
        )
        return _row_to_deposit(row) if row else None

    async def get_by_bank_reference(
        self, bank_reference: str
    ) -> Optional[DepositRequest]:
        row = await self._conn.fetchrow(
            "SELECT * FROM finance.deposits WHERE bank_reference = $1", bank_reference
        )
        return _row_to_deposit(row) if row else None

    async def update_status(
        self,
        deposit_id: str,
        new_status: DepositStatus,
        note: str = "",
        **kwargs,
    ) -> None:
        allowed_extra = {
            "tx_hash",
            "confirmations",
            "step_fn_execution_arn",
            "credited_at",
        }
        set_parts = ["status = $2", "updated_at = NOW()"]
        params: list = [deposit_id, new_status.value]
        i = 3
        for key, val in kwargs.items():
            if key in allowed_extra:
                set_parts.append(f"{key} = ${i}")
                params.append(val)
                i += 1

        row = await self._conn.fetchrow(
            "SELECT status FROM finance.deposits WHERE id = $1", deposit_id
        )
        prev_status = row["status"] if row else None

        async with self._conn.transaction():
            await self._conn.execute(
                f"UPDATE finance.deposits SET {', '.join(set_parts)} WHERE id = $1",
                *params,
            )
            await self._conn.execute(
                """
                INSERT INTO finance.deposit_audit_log
                  (deposit_id, from_status, to_status, note)
                VALUES ($1, $2, $3, $4)
                """,
                deposit_id,
                prev_status,
                new_status.value,
                note,
            )

    async def list_by_user(
        self, user_id: str, limit: int = 50
    ) -> list[DepositRequest]:
        rows = await self._conn.fetch(
            "SELECT * FROM finance.deposits "
            "WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
            user_id,
            limit,
        )
        return [_row_to_deposit(r) for r in rows]

    async def get_expired(self) -> list[DepositRequest]:
        rows = await self._conn.fetch(
            "SELECT * FROM finance.deposits "
            "WHERE status = 'PENDING' AND expires_at < NOW()"
        )
        return [_row_to_deposit(r) for r in rows]


def _row_to_deposit(row) -> DepositRequest:
    return DepositRequest(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        type=DepositType(row["type"]),
        asset=row["asset"],
        amount=Decimal(str(row["amount"])),
        status=DepositStatus(row["status"]),
        wallet_address=row["wallet_address"],
        tx_hash=row["tx_hash"],
        bank_reference=row["bank_reference"],
        confirmations=row["confirmations"],
        required_confirmations=row["required_confirmations"],
        step_fn_execution_arn=row["step_fn_execution_arn"],
        credited_at=row["credited_at"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
