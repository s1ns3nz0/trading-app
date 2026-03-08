from abc import ABC, abstractmethod
from decimal import Decimal
from typing import List, Optional

from ..models.domain import WithdrawalRequest, WithdrawalStatus, WithdrawalType


class WithdrawalRepository(ABC):

    @abstractmethod
    async def create(self, w: WithdrawalRequest) -> WithdrawalRequest: ...

    @abstractmethod
    async def get(self, withdrawal_id: str) -> Optional[WithdrawalRequest]: ...

    @abstractmethod
    async def update_status(
        self,
        withdrawal_id: str,
        new_status: WithdrawalStatus,
        note: str = "",
        **kwargs,   # tx_hash, rejection_reason, step_fn_execution_arn, reserved_at, executed_at
    ) -> None: ...

    @abstractmethod
    async def list_by_user(
        self, user_id: str, limit: int = 50
    ) -> List[WithdrawalRequest]: ...

    @abstractmethod
    async def get_daily_executed_sum(
        self, user_id: str, asset: str
    ) -> Decimal:
        """Sum of EXECUTED withdrawals in last 24h for AML check."""
        ...

    @abstractmethod
    async def get_cancellable(
        self, withdrawal_id: str, user_id: str
    ) -> Optional[WithdrawalRequest]:
        """Fetch withdrawal only if PENDING and owned by user."""
        ...


class PostgresWithdrawalRepository(WithdrawalRepository):
    def __init__(self, conn) -> None:
        self._conn = conn

    async def create(self, w: WithdrawalRequest) -> WithdrawalRequest:
        row = await self._conn.fetchrow(
            """
            INSERT INTO finance.withdrawals
              (id, user_id, type, asset, amount, to_address,
               bank_account_number, bank_routing_number, expires_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            RETURNING *
            """,
            w.id, w.user_id, w.type.value, w.asset, str(w.amount),
            w.to_address, w.bank_account_number, w.bank_routing_number,
            w.expires_at,
        )
        return _row_to_withdrawal(row)

    async def get(self, withdrawal_id: str) -> Optional[WithdrawalRequest]:
        row = await self._conn.fetchrow(
            "SELECT * FROM finance.withdrawals WHERE id = $1", withdrawal_id
        )
        return _row_to_withdrawal(row) if row else None

    async def update_status(
        self,
        withdrawal_id: str,
        new_status: WithdrawalStatus,
        note: str = "",
        **kwargs,
    ) -> None:
        allowed = {
            "tx_hash", "rejection_reason", "step_fn_execution_arn",
            "reserved_at", "executed_at",
        }
        set_parts = ["status = $2", "updated_at = NOW()"]
        params: list = [withdrawal_id, new_status.value]
        i = 3
        for key, val in kwargs.items():
            if key in allowed:
                set_parts.append(f"{key} = ${i}")
                params.append(val)
                i += 1

        row = await self._conn.fetchrow(
            "SELECT status FROM finance.withdrawals WHERE id = $1",
            withdrawal_id,
        )
        prev_status = row["status"] if row else None

        async with self._conn.transaction():
            await self._conn.execute(
                f"UPDATE finance.withdrawals SET {', '.join(set_parts)} WHERE id = $1",
                *params,
            )
            await self._conn.execute(
                """
                INSERT INTO finance.withdrawal_audit_log
                  (withdrawal_id, from_status, to_status, note)
                VALUES ($1, $2, $3, $4)
                """,
                withdrawal_id, prev_status, new_status.value, note,
            )

    async def list_by_user(
        self, user_id: str, limit: int = 50
    ) -> list[WithdrawalRequest]:
        rows = await self._conn.fetch(
            "SELECT * FROM finance.withdrawals "
            "WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
            user_id, limit,
        )
        return [_row_to_withdrawal(r) for r in rows]

    async def get_daily_executed_sum(
        self, user_id: str, asset: str
    ) -> Decimal:
        row = await self._conn.fetchrow(
            """
            SELECT COALESCE(SUM(amount), 0) AS total
            FROM finance.withdrawals
            WHERE user_id = $1
              AND asset   = $2
              AND status  = 'EXECUTED'
              AND created_at >= NOW() - INTERVAL '24 hours'
            """,
            user_id, asset,
        )
        return Decimal(str(row["total"]))

    async def get_cancellable(
        self, withdrawal_id: str, user_id: str
    ) -> Optional[WithdrawalRequest]:
        row = await self._conn.fetchrow(
            "SELECT * FROM finance.withdrawals "
            "WHERE id = $1 AND user_id = $2 AND status = 'PENDING'",
            withdrawal_id, user_id,
        )
        return _row_to_withdrawal(row) if row else None


def _row_to_withdrawal(row) -> WithdrawalRequest:
    return WithdrawalRequest(
        id=str(row["id"]),
        user_id=str(row["user_id"]),
        type=WithdrawalType(row["type"]),
        asset=row["asset"],
        amount=Decimal(str(row["amount"])),
        status=WithdrawalStatus(row["status"]),
        to_address=row["to_address"],
        tx_hash=row["tx_hash"],
        bank_account_number=row["bank_account_number"],
        bank_routing_number=row["bank_routing_number"],
        rejection_reason=row["rejection_reason"],
        step_fn_execution_arn=row["step_fn_execution_arn"],
        reserved_at=row["reserved_at"],
        executed_at=row["executed_at"],
        expires_at=row["expires_at"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )
