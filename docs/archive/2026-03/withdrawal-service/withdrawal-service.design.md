# Design: withdrawal-service

> **Feature**: withdrawal-service
> **Plan**: [withdrawal-service.plan.md](../../01-plan/features/withdrawal-service.plan.md)
> **Created**: 2026-03-08
> **Phase**: Design
> **Level**: Enterprise

---

## 1. Service Layout

```
services/withdrawal/
├── app/
│   ├── main.py                          # FastAPI app + lifespan
│   ├── config.py                        # Settings (pydantic-settings)
│   ├── schemas.py                       # Request/Response Pydantic models
│   ├── models/
│   │   └── domain.py                    # WithdrawalRequest, WithdrawalType, WithdrawalStatus
│   ├── repositories/
│   │   └── withdrawal_repo.py           # WithdrawalRepository ABC + PostgresWithdrawalRepository
│   ├── services/
│   │   ├── withdrawal_service.py        # Core business logic
│   │   ├── aml_service.py               # AML daily limit enforcement
│   │   └── step_fn_service.py           # Step Functions execution management
│   ├── producers/
│   │   └── eventbridge_producer.py      # EventBridge publish
│   ├── routers/
│   │   └── withdrawals.py               # User-facing CRUD endpoints
│   └── middleware/
│       └── auth.py                      # X-User-Id header validation
├── migrations/
│   └── versions/
│       └── 001_initial_schema.py        # Alembic migration
├── infra/
│   ├── ecs.tf
│   ├── step_functions.tf
│   ├── step_functions_asl.json
│   ├── eventbridge.tf
│   ├── iam.tf
│   └── variables.tf
└── tests/
    ├── conftest.py
    ├── test_withdrawal_service.py
    ├── test_aml_service.py
    └── test_withdrawals_router.py
```

---

## 2. Domain Model

### 2.1 Enums + Constants

```python
# app/models/domain.py
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


class WithdrawalType(str, Enum):
    CRYPTO = "CRYPTO"
    FIAT   = "FIAT"


class WithdrawalStatus(str, Enum):
    PENDING    = "PENDING"
    PROCESSING = "PROCESSING"
    EXECUTED   = "EXECUTED"
    REJECTED   = "REJECTED"
    FAILED     = "FAILED"
    CANCELLED  = "CANCELLED"


# Per-transaction minimum amounts
MINIMUM_AMOUNTS: dict[str, Decimal] = {
    "ETH":  Decimal("0.001"),
    "BTC":  Decimal("0.0001"),
    "USDT": Decimal("10"),
    "USD":  Decimal("10"),
}

# Per-transaction maximum amounts
MAXIMUM_AMOUNTS: dict[str, Decimal] = {
    "ETH":  Decimal("10"),
    "BTC":  Decimal("1"),
    "USDT": Decimal("50000"),
    "USD":  Decimal("50000"),
}

# Daily rolling limit in USD equivalent
DAILY_LIMIT_USD = Decimal("50000")

# Approximate USD rates (mock — real implementation uses price oracle)
USD_RATES: dict[str, Decimal] = {
    "ETH":  Decimal("3000"),
    "BTC":  Decimal("60000"),
    "USDT": Decimal("1"),
    "USD":  Decimal("1"),
}


@dataclass
class WithdrawalRequest:
    id:                    str
    user_id:               str
    type:                  WithdrawalType
    asset:                 str
    amount:                Decimal
    status:                WithdrawalStatus = WithdrawalStatus.PENDING
    to_address:            Optional[str]    = None   # crypto: destination
    tx_hash:               Optional[str]    = None   # crypto: on-chain tx
    bank_account_number:   Optional[str]    = None   # fiat: account
    bank_routing_number:   Optional[str]    = None   # fiat: routing
    rejection_reason:      Optional[str]    = None
    step_fn_execution_arn: Optional[str]    = None
    reserved_at:           Optional[datetime] = None
    executed_at:           Optional[datetime] = None
    expires_at:            Optional[datetime] = None
    created_at:            Optional[datetime] = None
    updated_at:            Optional[datetime] = None

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())
```

---

## 3. Database Schema

### 3.1 Alembic Migration — `001_initial_schema.py`

```python
"""Initial schema: withdrawals + withdrawal_audit_log"""
from alembic import op

revision = "001"
down_revision = None


def upgrade():
    # Schema already exists from deposit-service migration
    op.execute(
        "CREATE TYPE finance.withdrawal_type AS ENUM ('CRYPTO', 'FIAT')"
    )
    op.execute(
        """
        CREATE TYPE finance.withdrawal_status AS ENUM (
            'PENDING', 'PROCESSING', 'EXECUTED', 'REJECTED', 'FAILED', 'CANCELLED'
        )
        """
    )

    op.execute(
        """
        CREATE TABLE finance.withdrawals (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id               VARCHAR(64)               NOT NULL,
            type                  finance.withdrawal_type   NOT NULL,
            asset                 VARCHAR(10)               NOT NULL,
            amount                NUMERIC(20, 8)            NOT NULL,
            status                finance.withdrawal_status NOT NULL DEFAULT 'PENDING',
            to_address            VARCHAR(128),
            tx_hash               VARCHAR(128),
            bank_account_number   VARCHAR(64),
            bank_routing_number   VARCHAR(32),
            rejection_reason      TEXT,
            step_fn_execution_arn VARCHAR(2048),
            reserved_at           TIMESTAMPTZ,
            executed_at           TIMESTAMPTZ,
            expires_at            TIMESTAMPTZ               NOT NULL,
            created_at            TIMESTAMPTZ               NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ               NOT NULL DEFAULT NOW(),

            CONSTRAINT withdrawals_tx_hash_unique UNIQUE (tx_hash),
            CONSTRAINT withdrawals_amount_positive CHECK (amount > 0)
        )
        """
    )

    op.execute(
        "CREATE INDEX idx_withdrawals_user_id "
        "ON finance.withdrawals (user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_withdrawals_status "
        "ON finance.withdrawals (status, expires_at)"
    )
    op.execute(
        # For AML daily sum query
        "CREATE INDEX idx_withdrawals_aml "
        "ON finance.withdrawals (user_id, asset, status, created_at)"
    )

    op.execute(
        """
        CREATE TABLE finance.withdrawal_audit_log (
            id            BIGSERIAL PRIMARY KEY,
            withdrawal_id UUID                      NOT NULL REFERENCES finance.withdrawals(id),
            from_status   finance.withdrawal_status,
            to_status     finance.withdrawal_status NOT NULL,
            note          TEXT,
            created_at    TIMESTAMPTZ               NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_withdrawal_audit_id "
        "ON finance.withdrawal_audit_log (withdrawal_id, created_at DESC)"
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS finance.withdrawal_audit_log")
    op.execute("DROP TABLE IF EXISTS finance.withdrawals")
    op.execute("DROP TYPE IF EXISTS finance.withdrawal_status")
    op.execute("DROP TYPE IF EXISTS finance.withdrawal_type")
```

---

## 4. Repository Layer

### 4.1 Interface

```python
# app/repositories/withdrawal_repo.py
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import List, Optional

from ..models.domain import WithdrawalRequest, WithdrawalStatus


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
```

### 4.2 Implementation

```python
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
```

---

## 5. AML Service

```python
# app/services/aml_service.py
from decimal import Decimal
from ..models.domain import DAILY_LIMIT_USD, USD_RATES
from ..repositories.withdrawal_repo import WithdrawalRepository


class AMLService:
    def __init__(self, repo: WithdrawalRepository) -> None:
        self._repo = repo

    def usd_equivalent(self, asset: str, amount: Decimal) -> Decimal:
        rate = USD_RATES.get(asset, Decimal("1"))
        return amount * rate

    async def check_daily_limit(
        self, user_id: str, asset: str, amount: Decimal
    ) -> bool:
        """
        Returns True if withdrawal is within AML daily limit.
        Sums all EXECUTED withdrawals (any asset) in last 24h as USD equivalent.
        """
        # Sum existing daily USD-equivalent for all assets
        existing_usd = Decimal("0")
        for a in ("ETH", "BTC", "USDT", "USD"):
            asset_sum = await self._repo.get_daily_executed_sum(user_id, a)
            existing_usd += self.usd_equivalent(a, asset_sum)

        new_usd = self.usd_equivalent(asset, amount)
        return (existing_usd + new_usd) <= DAILY_LIMIT_USD
```

---

## 6. Step Functions Service

```python
# app/services/step_fn_service.py
import json
import boto3
from ..config import settings


class StepFnService:
    def __init__(self):
        self._client = boto3.client(
            "stepfunctions", region_name=settings.aws_region
        )

    async def start_execution(self, withdrawal_id: str) -> str:
        """Start execution; withdrawal_id as name = idempotency key."""
        resp = self._client.start_execution(
            stateMachineArn=settings.step_fn_arn,
            name=withdrawal_id,
            input=json.dumps({"withdrawalId": withdrawal_id}),
        )
        return resp["executionArn"]
```

---

## 7. EventBridge Producer

```python
# app/producers/eventbridge_producer.py
import json
from datetime import datetime, timezone
import boto3
from ..config import settings
from ..models.domain import WithdrawalRequest


class EventBridgeProducer:
    def __init__(self):
        self._client = boto3.client("events", region_name=settings.aws_region)

    async def publish_withdrawal_executed(self, w: WithdrawalRequest) -> None:
        executed_at = (
            w.executed_at.isoformat()
            if w.executed_at
            else datetime.now(timezone.utc).isoformat()
        )
        self._client.put_events(
            Entries=[{
                "Source":       "finance.withdrawal",
                "DetailType":   "WithdrawalExecuted",
                "EventBusName": settings.eventbridge_bus_name,
                "Detail": json.dumps({
                    "withdrawal_id": w.id,
                    "user_id":       w.user_id,
                    "asset":         w.asset,
                    "amount":        str(w.amount),
                    "tx_hash":       w.tx_hash,
                    "executed_at":   executed_at,
                }),
            }]
        )
```

---

## 8. Withdrawal Service (Core Logic)

```python
# app/services/withdrawal_service.py
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import httpx

from ..config import settings
from ..models.domain import (
    MAXIMUM_AMOUNTS, MINIMUM_AMOUNTS,
    WithdrawalRequest, WithdrawalStatus, WithdrawalType,
)
from ..repositories.withdrawal_repo import WithdrawalRepository
from ..services.aml_service import AMLService
from ..services.step_fn_service import StepFnService


class WithdrawalService:
    def __init__(
        self,
        repo: Optional[WithdrawalRepository],
        aml_svc: AMLService,
        step_fn_svc: StepFnService,
    ) -> None:
        self._repo     = repo
        self._aml      = aml_svc
        self._step_fn  = step_fn_svc

    # ── Create ─────────────────────────────────────────────────────────────────

    async def create_crypto_withdrawal(
        self,
        user_id: str,
        asset: str,
        amount: Decimal,
        to_address: str,
    ) -> WithdrawalRequest:
        _validate_amount(asset, amount)
        _validate_crypto_address(to_address, asset)
        if not await self._aml.check_daily_limit(user_id, asset, amount):
            raise ValueError("Daily withdrawal limit exceeded")

        w = WithdrawalRequest(
            id=WithdrawalRequest.new_id(),
            user_id=user_id,
            type=WithdrawalType.CRYPTO,
            asset=asset,
            amount=amount,
            to_address=to_address,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        return await self._repo.create(w)

    async def create_fiat_withdrawal(
        self,
        user_id: str,
        amount: Decimal,
        bank_account_number: str,
        bank_routing_number: str,
    ) -> WithdrawalRequest:
        _validate_amount("USD", amount)
        if not await self._aml.check_daily_limit(user_id, "USD", amount):
            raise ValueError("Daily withdrawal limit exceeded")

        w = WithdrawalRequest(
            id=WithdrawalRequest.new_id(),
            user_id=user_id,
            type=WithdrawalType.FIAT,
            asset="USD",
            amount=amount,
            bank_account_number=bank_account_number,
            bank_routing_number=bank_routing_number,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        return await self._repo.create(w)

    # ── Reserve (called by Step Functions) ─────────────────────────────────────

    async def reserve_balance(self, withdrawal_id: str) -> None:
        """
        Deduct balance from spot-trading available balance.
        Updates status PENDING → PROCESSING on success.
        Raises ValueError if deduct fails (insufficient funds).
        """
        w = await self._repo.get(withdrawal_id)
        if not w:
            raise ValueError(f"Withdrawal {withdrawal_id} not found")
        if w.status != WithdrawalStatus.PENDING:
            return   # idempotent

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.spot_trading_internal_url}/internal/positions/deduct",
                headers={"X-Internal-Token": settings.internal_token},
                json={
                    "user_id":       w.user_id,
                    "asset":         w.asset,
                    "amount":        str(w.amount),
                    "withdrawal_id": w.id,
                },
            )
            if resp.status_code == 422:
                raise ValueError("Insufficient balance")
            resp.raise_for_status()

        now = datetime.now(timezone.utc)
        await self._repo.update_status(
            w.id,
            WithdrawalStatus.PROCESSING,
            note="Balance reserved — deducted from spot-trading",
            reserved_at=now,
        )

    # ── Execute ────────────────────────────────────────────────────────────────

    async def execute_crypto(self, withdrawal_id: str) -> None:
        """Mock on-chain send. Generates deterministic tx_hash."""
        w = await self._repo.get(withdrawal_id)
        if not w:
            raise ValueError(f"Withdrawal {withdrawal_id} not found")
        if w.status == WithdrawalStatus.EXECUTED:
            return   # idempotent
        if w.status != WithdrawalStatus.PROCESSING:
            raise ValueError(f"Cannot execute in status {w.status}")

        # Mock: generate tx_hash (real: call hot wallet signing service)
        tx_hash = "0x" + secrets.token_hex(32)
        now = datetime.now(timezone.utc)

        await self._repo.update_status(
            w.id,
            WithdrawalStatus.EXECUTED,
            note=f"On-chain tx sent: {tx_hash}",
            tx_hash=tx_hash,
            executed_at=now,
        )

    async def execute_fiat(self, withdrawal_id: str) -> None:
        """Mock bank transfer initiation."""
        w = await self._repo.get(withdrawal_id)
        if not w:
            raise ValueError(f"Withdrawal {withdrawal_id} not found")
        if w.status == WithdrawalStatus.EXECUTED:
            return   # idempotent
        if w.status != WithdrawalStatus.PROCESSING:
            raise ValueError(f"Cannot execute in status {w.status}")

        now = datetime.now(timezone.utc)
        await self._repo.update_status(
            w.id,
            WithdrawalStatus.EXECUTED,
            note="Bank transfer initiated (mock)",
            executed_at=now,
        )

    # ── Reject / Fail / Cancel ─────────────────────────────────────────────────

    async def reject_withdrawal(
        self, withdrawal_id: str, reason: str
    ) -> None:
        """Reject (e.g., AML fail). Releases reserved balance if PROCESSING."""
        w = await self._repo.get(withdrawal_id)
        if not w:
            raise ValueError(f"Withdrawal {withdrawal_id} not found")

        await self._repo.update_status(
            w.id,
            WithdrawalStatus.REJECTED,
            note=f"Rejected: {reason}",
            rejection_reason=reason,
        )
        if w.status == WithdrawalStatus.PROCESSING:
            await self._release_balance(w)

    async def fail_withdrawal(
        self, withdrawal_id: str, reason: str
    ) -> None:
        """Mark as FAILED (execution error). Releases reserved balance."""
        w = await self._repo.get(withdrawal_id)
        if not w:
            raise ValueError(f"Withdrawal {withdrawal_id} not found")

        await self._repo.update_status(
            w.id,
            WithdrawalStatus.FAILED,
            note=f"Failed: {reason}",
        )
        if w.status == WithdrawalStatus.PROCESSING:
            await self._release_balance(w)

    async def cancel_withdrawal(
        self, withdrawal_id: str, user_id: str
    ) -> None:
        """User-initiated cancel. Only allowed in PENDING state."""
        w = await self._repo.get_cancellable(withdrawal_id, user_id)
        if not w:
            raise ValueError("Withdrawal not found or cannot be cancelled")

        await self._repo.update_status(
            w.id,
            WithdrawalStatus.CANCELLED,
            note="Cancelled by user",
        )

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _release_balance(self, w: WithdrawalRequest) -> None:
        """Credit balance back to spot-trading (reversal)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.spot_trading_internal_url}/internal/positions/credit",
                headers={"X-Internal-Token": settings.internal_token},
                json={
                    "user_id":       w.user_id,
                    "asset":         w.asset,
                    "amount":        str(w.amount),
                    "deposit_id":    w.id,   # reuse credit API (deposit_id field)
                },
            )
            resp.raise_for_status()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _validate_amount(asset: str, amount: Decimal) -> None:
    minimum = MINIMUM_AMOUNTS.get(asset)
    maximum = MAXIMUM_AMOUNTS.get(asset)
    if minimum and amount < minimum:
        raise ValueError(f"Amount below minimum {minimum} for {asset}")
    if maximum and amount > maximum:
        raise ValueError(f"Amount exceeds maximum {maximum} for {asset}")


def _validate_crypto_address(address: str, asset: str) -> None:
    if asset in ("ETH", "USDT"):
        if not (address.startswith("0x") and len(address) == 42):
            raise ValueError(f"Invalid {asset} address format")
    elif asset == "BTC":
        if not (address.startswith("bc1q") and len(address) == 42):
            raise ValueError("Invalid BTC address format")
    else:
        raise ValueError(f"Unknown asset {asset}")
```

---

## 9. FastAPI Application

### 9.1 Config

```python
# app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_url:                    str
    aws_region:                str   = "ap-northeast-2"
    step_fn_arn:               str   = ""
    eventbridge_bus_name:      str   = "finance-events"
    spot_trading_internal_url: str   = "http://spot-trading:8000"
    internal_token:            str   = "dev-internal-token"
    withdrawal_expiry_hours:   int   = 24

    class Config:
        env_file = ".env"


settings = Settings()
```

### 9.2 Schemas

```python
# app/schemas.py
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, field_validator


class CreateCryptoWithdrawalRequest(BaseModel):
    asset:      str
    amount:     str
    to_address: str

    @field_validator("asset")
    @classmethod
    def validate_asset(cls, v: str) -> str:
        if v not in ("ETH", "BTC", "USDT"):
            raise ValueError("asset must be ETH, BTC, or USDT")
        return v

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: str) -> str:
        if Decimal(v) <= 0:
            raise ValueError("amount must be positive")
        return v


class CreateFiatWithdrawalRequest(BaseModel):
    amount:             str
    bank_account_number: str
    bank_routing_number: str

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: str) -> str:
        if Decimal(v) <= 0:
            raise ValueError("amount must be positive")
        return v


class WithdrawalResponse(BaseModel):
    id:                  str
    type:                str
    asset:               str
    amount:              str
    status:              str
    to_address:          Optional[str] = None
    tx_hash:             Optional[str] = None
    bank_account_number: Optional[str] = None
    rejection_reason:    Optional[str] = None
    reserved_at:         Optional[datetime] = None
    executed_at:         Optional[datetime] = None
    expires_at:          datetime
    created_at:          datetime


class DeductRequest(BaseModel):
    """Internal: POST /internal/positions/deduct from withdrawal service."""
    user_id:       str
    asset:         str
    amount:        str
    withdrawal_id: str
```

### 9.3 Auth Middleware

```python
# app/middleware/auth.py
from fastapi import HTTPException, Request

INTERNAL_PATHS = ("/health",)


async def require_user_id(request: Request) -> str:
    if any(request.url.path.startswith(p) for p in INTERNAL_PATHS):
        return ""
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-Id header")
    return user_id
```

### 9.4 Withdrawals Router

```python
# app/routers/withdrawals.py
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Request

from ..middleware.auth import require_user_id
from ..models.domain import WithdrawalRequest
from ..schemas import (
    CreateCryptoWithdrawalRequest,
    CreateFiatWithdrawalRequest,
    WithdrawalResponse,
)

router = APIRouter(prefix="/withdrawals")


def _to_response(w: WithdrawalRequest) -> WithdrawalResponse:
    return WithdrawalResponse(
        id=w.id,
        type=w.type.value,
        asset=w.asset,
        amount=str(w.amount),
        status=w.status.value,
        to_address=w.to_address,
        tx_hash=w.tx_hash,
        bank_account_number=w.bank_account_number,
        rejection_reason=w.rejection_reason,
        reserved_at=w.reserved_at,
        executed_at=w.executed_at,
        expires_at=w.expires_at,
        created_at=w.created_at,
    )


@router.post("/crypto", response_model=WithdrawalResponse, status_code=201)
async def create_crypto_withdrawal(
    body: CreateCryptoWithdrawalRequest,
    user_id: str = Depends(require_user_id),
):
    from ..main import db_pool, withdrawal_svc
    from ..repositories.withdrawal_repo import PostgresWithdrawalRepository

    try:
        async with db_pool.acquire() as conn:
            withdrawal_svc._repo = PostgresWithdrawalRepository(conn)
            withdrawal_svc._aml._repo = PostgresWithdrawalRepository(conn)
            w = await withdrawal_svc.create_crypto_withdrawal(
                user_id, body.asset, Decimal(body.amount), body.to_address
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _to_response(w)


@router.post("/fiat", response_model=WithdrawalResponse, status_code=201)
async def create_fiat_withdrawal(
    body: CreateFiatWithdrawalRequest,
    user_id: str = Depends(require_user_id),
):
    from ..main import db_pool, withdrawal_svc
    from ..repositories.withdrawal_repo import PostgresWithdrawalRepository

    try:
        async with db_pool.acquire() as conn:
            withdrawal_svc._repo = PostgresWithdrawalRepository(conn)
            withdrawal_svc._aml._repo = PostgresWithdrawalRepository(conn)
            w = await withdrawal_svc.create_fiat_withdrawal(
                user_id, Decimal(body.amount),
                body.bank_account_number, body.bank_routing_number,
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _to_response(w)


@router.get("/{withdrawal_id}", response_model=WithdrawalResponse)
async def get_withdrawal(
    withdrawal_id: str,
    user_id: str = Depends(require_user_id),
):
    from ..main import db_pool
    from ..repositories.withdrawal_repo import PostgresWithdrawalRepository

    async with db_pool.acquire() as conn:
        w = await PostgresWithdrawalRepository(conn).get(withdrawal_id)
    if not w or w.user_id != user_id:
        raise HTTPException(status_code=404, detail="Withdrawal not found")
    return _to_response(w)


@router.get("", response_model=list[WithdrawalResponse])
async def list_withdrawals(user_id: str = Depends(require_user_id)):
    from ..main import db_pool
    from ..repositories.withdrawal_repo import PostgresWithdrawalRepository

    async with db_pool.acquire() as conn:
        withdrawals = await PostgresWithdrawalRepository(conn).list_by_user(user_id)
    return [_to_response(w) for w in withdrawals]


@router.delete("/{withdrawal_id}", status_code=204)
async def cancel_withdrawal(
    withdrawal_id: str,
    user_id: str = Depends(require_user_id),
):
    from ..main import db_pool, withdrawal_svc
    from ..repositories.withdrawal_repo import PostgresWithdrawalRepository

    try:
        async with db_pool.acquire() as conn:
            withdrawal_svc._repo = PostgresWithdrawalRepository(conn)
            await withdrawal_svc.cancel_withdrawal(withdrawal_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
```

### 9.5 Main Application

```python
# app/main.py
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI

from .config import settings
from .producers.eventbridge_producer import EventBridgeProducer
from .routers import withdrawals
from .services.aml_service import AMLService
from .services.step_fn_service import StepFnService
from .services.withdrawal_service import WithdrawalService

logger = logging.getLogger(__name__)

db_pool: asyncpg.Pool | None = None
withdrawal_svc: WithdrawalService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, withdrawal_svc

    db_pool = await asyncpg.create_pool(
        settings.db_url, min_size=3, max_size=15
    )

    aml_svc     = AMLService(repo=None)   # repo injected per request
    step_fn_svc = StepFnService()
    eb_producer = EventBridgeProducer()

    withdrawal_svc = WithdrawalService(
        repo=None,
        aml_svc=aml_svc,
        step_fn_svc=step_fn_svc,
    )

    logger.info("WithdrawalService started")
    yield

    await db_pool.close()


app = FastAPI(title="WithdrawalService", version="1.0.0", lifespan=lifespan)
app.include_router(withdrawals.router)


@app.get("/health")
async def health():
    return {"status": "ok", "db": db_pool is not None}
```

---

## 10. Step Functions State Machine (ASL)

```json
// infra/step_functions_asl.json
{
  "Comment": "Withdrawal execution workflow",
  "StartAt": "ReserveBalance",
  "States": {
    "ReserveBalance": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "${reserve_balance_fn_arn}",
        "Payload.$": "$"
      },
      "ResultPath": "$.reserveResult",
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed"],
          "MaxAttempts": 2,
          "IntervalSeconds": 5
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "Next": "RejectWithdrawal",
          "ResultPath": "$.error"
        }
      ],
      "Next": "ValidateAML"
    },
    "ValidateAML": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "${validate_aml_fn_arn}",
        "Payload.$": "$"
      },
      "ResultPath": "$.amlResult",
      "Next": "IsAMLPass"
    },
    "IsAMLPass": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.amlResult.Payload.pass",
          "BooleanEquals": true,
          "Next": "ExecuteWithdrawal"
        }
      ],
      "Default": "RejectWithdrawal"
    },
    "ExecuteWithdrawal": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "${execute_withdrawal_fn_arn}",
        "Payload.$": "$"
      },
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed"],
          "MaxAttempts": 3,
          "IntervalSeconds": 10,
          "BackoffRate": 2.0
        }
      ],
      "Catch": [
        {
          "ErrorEquals": ["States.ALL"],
          "Next": "FailWithdrawal",
          "ResultPath": "$.error"
        }
      ],
      "ResultPath": "$.executeResult",
      "Next": "PublishEvent"
    },
    "PublishEvent": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "${publish_event_fn_arn}",
        "Payload.$": "$"
      },
      "End": true
    },
    "RejectWithdrawal": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "${reject_withdrawal_fn_arn}",
        "Payload.$": "$"
      },
      "End": true
    },
    "FailWithdrawal": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "${fail_withdrawal_fn_arn}",
        "Payload.$": "$"
      },
      "End": true
    }
  },
  "TimeoutSeconds": 86400
}
```

---

## 11. Spot-Trading: Internal Deduct Endpoint (Addition)

```python
# services/spot-trading/app/routers/internal.py (addition to existing file)

@router.post("/positions/deduct", status_code=204)
async def deduct_position(request: Request):
    """
    Deduct from a user's available balance (withdrawal reservation).
    Returns 422 if insufficient balance.
    Called by the withdrawal service before Step Functions execution.

    Body: { user_id, asset, amount, withdrawal_id }
    """
    token = request.headers.get("X-Internal-Token", "")
    if token != settings.internal_token:
        raise HTTPException(status_code=401, detail="Invalid internal token")

    body = await request.json()
    user_id = body["user_id"]
    asset   = body["asset"]
    amount  = Decimal(str(body["amount"]))

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            repo = PositionRepository(conn)
            success = await repo.lock_for_order(user_id, asset, amount)
            if not success:
                raise HTTPException(
                    status_code=422, detail="Insufficient balance"
                )
```

---

## 12. Terraform Infrastructure

### `infra/step_functions.tf`

```hcl
resource "aws_sfn_state_machine" "withdrawal_workflow" {
  name     = "${var.env}-withdrawal-workflow"
  role_arn = aws_iam_role.step_fn.arn

  definition = templatefile("${path.module}/step_functions_asl.json", {
    reserve_balance_fn_arn    = aws_lambda_function.reserve_balance.arn
    validate_aml_fn_arn       = aws_lambda_function.validate_aml.arn
    execute_withdrawal_fn_arn = aws_lambda_function.execute_withdrawal.arn
    publish_event_fn_arn      = aws_lambda_function.publish_event.arn
    reject_withdrawal_fn_arn  = aws_lambda_function.reject_withdrawal.arn
    fail_withdrawal_fn_arn    = aws_lambda_function.fail_withdrawal.arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.step_fn.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }
}

resource "aws_cloudwatch_log_group" "step_fn" {
  name              = "/aws/states/${var.env}-withdrawal-workflow"
  retention_in_days = 30
}
```

### `infra/eventbridge.tf`

```hcl
# Reuses finance-events bus created by deposit-service

resource "aws_cloudwatch_event_rule" "withdrawal_executed" {
  name           = "${var.env}-withdrawal-executed"
  event_bus_name = var.finance_event_bus_name

  event_pattern = jsonencode({
    source      = ["finance.withdrawal"]
    detail-type = ["WithdrawalExecuted"]
  })
}

resource "aws_cloudwatch_event_target" "riskcompliance_bus" {
  rule           = aws_cloudwatch_event_rule.withdrawal_executed.name
  event_bus_name = var.finance_event_bus_name
  arn            = var.riskcompliance_event_bus_arn
  role_arn       = var.eventbridge_role_arn
}

resource "aws_cloudwatch_event_target" "notification_bus" {
  rule           = aws_cloudwatch_event_rule.withdrawal_executed.name
  event_bus_name = var.finance_event_bus_name
  arn            = var.notification_event_bus_arn
  role_arn       = var.eventbridge_role_arn
}
```

### `infra/iam.tf`

```hcl
data "aws_iam_policy_document" "ecs_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com", "lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ecs_task" {
  name               = "${var.env}-withdrawal-ecs-task"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy" "ecs_task_policy" {
  role = aws_iam_role.ecs_task.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["states:StartExecution"]
        Resource = [aws_sfn_state_machine.withdrawal_workflow.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["events:PutEvents"]
        Resource = ["arn:aws:events:${var.region}:${var.account_id}:event-bus/finance-events"]
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = ["arn:aws:secretsmanager:${var.region}:${var.account_id}:secret:withdrawal/*"]
      }
    ]
  })
}

data "aws_iam_policy_document" "sfn_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "step_fn" {
  name               = "${var.env}-withdrawal-step-fn"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
}

resource "aws_iam_role_policy" "step_fn_policy" {
  role = aws_iam_role.step_fn.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["lambda:InvokeFunction"]
      Resource = [
        aws_lambda_function.reserve_balance.arn,
        aws_lambda_function.validate_aml.arn,
        aws_lambda_function.execute_withdrawal.arn,
        aws_lambda_function.publish_event.arn,
        aws_lambda_function.reject_withdrawal.arn,
        aws_lambda_function.fail_withdrawal.arn,
      ]
    }]
  })
}
```

---

## 13. Tests

### `tests/conftest.py`

```python
import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from ..app.models.domain import WithdrawalRequest, WithdrawalType, WithdrawalStatus


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo._conn = AsyncMock()
    repo.create = AsyncMock()
    repo.get = AsyncMock()
    repo.update_status = AsyncMock()
    repo.list_by_user = AsyncMock(return_value=[])
    repo.get_daily_executed_sum = AsyncMock(return_value=Decimal("0"))
    repo.get_cancellable = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_aml(mock_repo):
    from ..app.services.aml_service import AMLService
    svc = AMLService(repo=mock_repo)
    return svc


@pytest.fixture
def mock_step_fn():
    svc = AsyncMock()
    svc.start_execution = AsyncMock(
        return_value="arn:aws:states:ap-northeast-2:123:execution:withdrawal-workflow:w-001"
    )
    return svc


@pytest.fixture
def pending_crypto_withdrawal():
    return WithdrawalRequest(
        id="w-uuid-001",
        user_id="user-001",
        type=WithdrawalType.CRYPTO,
        asset="ETH",
        amount=Decimal("0.5"),
        status=WithdrawalStatus.PENDING,
        to_address="0xabc123def456abc123def456abc123def456abc1",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def pending_fiat_withdrawal():
    return WithdrawalRequest(
        id="w-uuid-002",
        user_id="user-001",
        type=WithdrawalType.FIAT,
        asset="USD",
        amount=Decimal("500"),
        status=WithdrawalStatus.PENDING,
        bank_account_number="123456789",
        bank_routing_number="021000021",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
```

### `tests/test_withdrawal_service.py`

```python
"""
Tests — WithdrawalService core logic.

Coverage:
  TC-W01  create crypto withdrawal success
  TC-W02  create crypto below minimum → ValueError
  TC-W03  create crypto above maximum → ValueError
  TC-W04  create crypto invalid address → ValueError
  TC-W05  create crypto AML limit exceeded → ValueError
  TC-W06  create fiat withdrawal success
  TC-W07  reserve_balance success → PROCESSING
  TC-W08  reserve_balance insufficient funds → ValueError
  TC-W09  reserve_balance idempotent (already PROCESSING)
  TC-W10  execute_crypto success → EXECUTED with tx_hash
  TC-W11  execute_crypto idempotent (already EXECUTED)
  TC-W12  execute_fiat success → EXECUTED
  TC-W13  reject_withdrawal releases balance (PROCESSING → REJECTED)
  TC-W14  fail_withdrawal releases balance (PROCESSING → FAILED)
  TC-W15  cancel_withdrawal PENDING → CANCELLED
  TC-W16  cancel_withdrawal PROCESSING → ValueError (409)
"""
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from ..app.services.withdrawal_service import WithdrawalService
from ..app.models.domain import WithdrawalStatus, WithdrawalType


@pytest.fixture
def svc(mock_repo, mock_aml, mock_step_fn):
    return WithdrawalService(mock_repo, mock_aml, mock_step_fn)


# TC-W01
@pytest.mark.asyncio
async def test_create_crypto_withdrawal_success(svc, mock_repo, pending_crypto_withdrawal):
    mock_repo.create.return_value = pending_crypto_withdrawal
    result = await svc.create_crypto_withdrawal(
        "user-001", "ETH", Decimal("0.5"),
        "0xabc123def456abc123def456abc123def456abc1"
    )
    assert result.asset == "ETH"
    assert result.to_address is not None
    mock_repo.create.assert_called_once()


# TC-W02
@pytest.mark.asyncio
async def test_create_crypto_below_minimum(svc):
    with pytest.raises(ValueError, match="below minimum"):
        await svc.create_crypto_withdrawal(
            "user-001", "ETH", Decimal("0.0001"),
            "0xabc123def456abc123def456abc123def456abc1"
        )


# TC-W03
@pytest.mark.asyncio
async def test_create_crypto_above_maximum(svc):
    with pytest.raises(ValueError, match="exceeds maximum"):
        await svc.create_crypto_withdrawal(
            "user-001", "ETH", Decimal("100"),
            "0xabc123def456abc123def456abc123def456abc1"
        )


# TC-W04
@pytest.mark.asyncio
async def test_create_crypto_invalid_address(svc):
    with pytest.raises(ValueError, match="Invalid ETH address"):
        await svc.create_crypto_withdrawal(
            "user-001", "ETH", Decimal("0.5"), "not-an-address"
        )


# TC-W05
@pytest.mark.asyncio
async def test_create_crypto_aml_exceeded(svc, mock_repo):
    mock_repo.get_daily_executed_sum.return_value = Decimal("20")  # 20 ETH = $60k
    with pytest.raises(ValueError, match="Daily withdrawal limit"):
        await svc.create_crypto_withdrawal(
            "user-001", "ETH", Decimal("0.5"),
            "0xabc123def456abc123def456abc123def456abc1"
        )


# TC-W06
@pytest.mark.asyncio
async def test_create_fiat_withdrawal_success(svc, mock_repo, pending_fiat_withdrawal):
    mock_repo.create.return_value = pending_fiat_withdrawal
    result = await svc.create_fiat_withdrawal(
        "user-001", Decimal("500"), "123456789", "021000021"
    )
    assert result.asset == "USD"
    assert result.bank_account_number == "123456789"


# TC-W07
@pytest.mark.asyncio
async def test_reserve_balance_success(svc, mock_repo, pending_crypto_withdrawal):
    mock_repo.get.return_value = pending_crypto_withdrawal

    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.raise_for_status = MagicMock()
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_resp
        )
        await svc.reserve_balance(pending_crypto_withdrawal.id)

    mock_repo.update_status.assert_called_once()
    assert mock_repo.update_status.call_args.args[1] == WithdrawalStatus.PROCESSING


# TC-W08
@pytest.mark.asyncio
async def test_reserve_balance_insufficient_funds(svc, mock_repo, pending_crypto_withdrawal):
    mock_repo.get.return_value = pending_crypto_withdrawal

    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_resp
        )
        with pytest.raises(ValueError, match="Insufficient balance"):
            await svc.reserve_balance(pending_crypto_withdrawal.id)


# TC-W09
@pytest.mark.asyncio
async def test_reserve_balance_idempotent(svc, mock_repo, pending_crypto_withdrawal):
    pending_crypto_withdrawal.status = WithdrawalStatus.PROCESSING
    mock_repo.get.return_value = pending_crypto_withdrawal
    await svc.reserve_balance(pending_crypto_withdrawal.id)
    mock_repo.update_status.assert_not_called()


# TC-W10
@pytest.mark.asyncio
async def test_execute_crypto_success(svc, mock_repo, pending_crypto_withdrawal):
    pending_crypto_withdrawal.status = WithdrawalStatus.PROCESSING
    mock_repo.get.return_value = pending_crypto_withdrawal
    await svc.execute_crypto(pending_crypto_withdrawal.id)
    mock_repo.update_status.assert_called_once()
    call = mock_repo.update_status.call_args
    assert call.args[1] == WithdrawalStatus.EXECUTED
    assert call.kwargs.get("tx_hash", "").startswith("0x")


# TC-W11
@pytest.mark.asyncio
async def test_execute_crypto_idempotent(svc, mock_repo, pending_crypto_withdrawal):
    pending_crypto_withdrawal.status = WithdrawalStatus.EXECUTED
    mock_repo.get.return_value = pending_crypto_withdrawal
    await svc.execute_crypto(pending_crypto_withdrawal.id)
    mock_repo.update_status.assert_not_called()


# TC-W12
@pytest.mark.asyncio
async def test_execute_fiat_success(svc, mock_repo, pending_fiat_withdrawal):
    pending_fiat_withdrawal.status = WithdrawalStatus.PROCESSING
    mock_repo.get.return_value = pending_fiat_withdrawal
    await svc.execute_fiat(pending_fiat_withdrawal.id)
    mock_repo.update_status.assert_called_once()
    assert mock_repo.update_status.call_args.args[1] == WithdrawalStatus.EXECUTED


# TC-W13
@pytest.mark.asyncio
async def test_reject_releases_balance(svc, mock_repo, pending_crypto_withdrawal):
    pending_crypto_withdrawal.status = WithdrawalStatus.PROCESSING
    mock_repo.get.return_value = pending_crypto_withdrawal

    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_resp
        )
        await svc.reject_withdrawal(pending_crypto_withdrawal.id, "AML limit exceeded")

    assert mock_repo.update_status.call_args.args[1] == WithdrawalStatus.REJECTED
    mock_resp.raise_for_status.assert_called_once()   # credit called


# TC-W14
@pytest.mark.asyncio
async def test_fail_releases_balance(svc, mock_repo, pending_crypto_withdrawal):
    pending_crypto_withdrawal.status = WithdrawalStatus.PROCESSING
    mock_repo.get.return_value = pending_crypto_withdrawal

    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_resp
        )
        await svc.fail_withdrawal(pending_crypto_withdrawal.id, "Execution error")

    assert mock_repo.update_status.call_args.args[1] == WithdrawalStatus.FAILED


# TC-W15
@pytest.mark.asyncio
async def test_cancel_pending(svc, mock_repo, pending_crypto_withdrawal):
    mock_repo.get_cancellable.return_value = pending_crypto_withdrawal
    await svc.cancel_withdrawal(pending_crypto_withdrawal.id, "user-001")
    assert mock_repo.update_status.call_args.args[1] == WithdrawalStatus.CANCELLED


# TC-W16
@pytest.mark.asyncio
async def test_cancel_processing_raises(svc, mock_repo):
    mock_repo.get_cancellable.return_value = None
    with pytest.raises(ValueError, match="cannot be cancelled"):
        await svc.cancel_withdrawal("w-uuid-001", "user-001")
```

### `tests/test_aml_service.py`

```python
"""
Tests — AMLService daily limit logic.

  TC-A01  under limit → True
  TC-A02  exactly at limit → True
  TC-A03  one cent over limit → False
  TC-A04  multi-asset aggregation
"""
import pytest
from decimal import Decimal
from ..app.services.aml_service import AMLService


@pytest.fixture
def aml(mock_repo):
    return AMLService(repo=mock_repo)


# TC-A01
@pytest.mark.asyncio
async def test_under_limit(aml, mock_repo):
    mock_repo.get_daily_executed_sum.return_value = Decimal("0")
    result = await aml.check_daily_limit("user-001", "USD", Decimal("1000"))
    assert result is True


# TC-A02
@pytest.mark.asyncio
async def test_exactly_at_limit(aml, mock_repo):
    mock_repo.get_daily_executed_sum.return_value = Decimal("0")
    result = await aml.check_daily_limit("user-001", "USD", Decimal("50000"))
    assert result is True


# TC-A03
@pytest.mark.asyncio
async def test_over_limit(aml, mock_repo):
    mock_repo.get_daily_executed_sum.return_value = Decimal("0")
    result = await aml.check_daily_limit("user-001", "USD", Decimal("50000.01"))
    assert result is False


# TC-A04
@pytest.mark.asyncio
async def test_multi_asset_aggregation(aml, mock_repo):
    # Already executed $45k equivalent (15 ETH @ $3000)
    async def side_effect(user_id, asset):
        if asset == "ETH":
            return Decimal("15")   # 15 ETH = $45,000
        return Decimal("0")
    mock_repo.get_daily_executed_sum.side_effect = side_effect

    # Try to withdraw $6k more (2 ETH)
    result = await aml.check_daily_limit("user-001", "ETH", Decimal("2"))
    assert result is False   # 45k + 6k = 51k > 50k limit
```

---

## 14. Frontend

### `apps/web/src/services/financeApi.ts` (additions)

```typescript
export interface WithdrawalResponse {
  id: string
  type: 'CRYPTO' | 'FIAT'
  asset: string
  amount: string
  status: 'PENDING' | 'PROCESSING' | 'EXECUTED' | 'REJECTED' | 'FAILED' | 'CANCELLED'
  toAddress?: string
  txHash?: string
  bankAccountNumber?: string
  rejectionReason?: string
  reservedAt?: string
  executedAt?: string
  expiresAt: string
  createdAt: string
}

export async function createCryptoWithdrawal(
  asset: string,
  amount: string,
  toAddress: string,
  token: string,
): Promise<WithdrawalResponse> {
  const res = await fetch(`${FINANCE_API}/withdrawals/crypto`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ asset, amount, to_address: toAddress }),
  })
  if (!res.ok) { const err = await res.json(); throw new Error(err.detail ?? 'Failed') }
  return res.json()
}

export async function createFiatWithdrawal(
  amount: string,
  bankAccountNumber: string,
  bankRoutingNumber: string,
  token: string,
): Promise<WithdrawalResponse> {
  const res = await fetch(`${FINANCE_API}/withdrawals/fiat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ amount, bank_account_number: bankAccountNumber, bank_routing_number: bankRoutingNumber }),
  })
  if (!res.ok) { const err = await res.json(); throw new Error(err.detail ?? 'Failed') }
  return res.json()
}

export async function getWithdrawalById(id: string, token: string): Promise<WithdrawalResponse> {
  const res = await fetch(`${FINANCE_API}/withdrawals/${id}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Withdrawal not found')
  return res.json()
}

export async function cancelWithdrawalById(id: string, token: string): Promise<void> {
  const res = await fetch(`${FINANCE_API}/withdrawals/${id}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok && res.status !== 204) {
    const err = await res.json()
    throw new Error(err.detail ?? 'Cannot cancel')
  }
}
```

### `apps/web/src/hooks/useWithdrawal.ts`

```typescript
'use client'

import { useEffect, useRef, useState } from 'react'
import { getWithdrawalById, WithdrawalResponse } from '../services/financeApi'

const TERMINAL_STATUSES = new Set(['EXECUTED', 'REJECTED', 'FAILED', 'CANCELLED'])
const POLL_INTERVAL_MS = 10_000

export function useWithdrawal(withdrawalId: string | null, token: string) {
  const [withdrawal, setWithdrawal] = useState<WithdrawalResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    if (!withdrawalId) return

    const fetch = async () => {
      try {
        const w = await getWithdrawalById(withdrawalId, token)
        setWithdrawal(w)
        if (TERMINAL_STATUSES.has(w.status)) {
          if (intervalRef.current) clearInterval(intervalRef.current)
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error')
      }
    }

    fetch()
    intervalRef.current = setInterval(fetch, POLL_INTERVAL_MS)
    return () => { if (intervalRef.current) clearInterval(intervalRef.current) }
  }, [withdrawalId, token])

  return { withdrawal, error }
}
```

### `apps/web/src/app/(app)/withdraw/page.tsx`

```typescript
'use client'

import { useState } from 'react'
import { useAuthStore } from '../../../stores/authStore'
import { useWithdrawal } from '../../../hooks/useWithdrawal'
import {
  createCryptoWithdrawal,
  createFiatWithdrawal,
  cancelWithdrawalById,
  WithdrawalResponse,
} from '../../../services/financeApi'

type Tab = 'CRYPTO' | 'FIAT'
type Asset = 'ETH' | 'BTC' | 'USDT'

function statusColor(status: string): string {
  if (status === 'EXECUTED') return 'text-up'
  if (status === 'REJECTED' || status === 'FAILED') return 'text-down'
  if (status === 'CANCELLED') return 'text-text-secondary'
  return 'text-accent'
}

export default function WithdrawPage() {
  const { tokens } = useAuthStore()
  const accessToken = tokens?.access_token ?? ''

  const [tab, setTab] = useState<Tab>('CRYPTO')
  const [asset, setAsset] = useState<Asset>('ETH')
  const [amount, setAmount] = useState('')
  const [toAddress, setToAddress] = useState('')
  const [bankAccount, setBankAccount] = useState('')
  const [bankRouting, setBankRouting] = useState('')
  const [withdrawalId, setWithdrawalId] = useState<string | null>(null)
  const [created, setCreated] = useState<WithdrawalResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const { withdrawal } = useWithdrawal(withdrawalId, accessToken)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const result = tab === 'CRYPTO'
        ? await createCryptoWithdrawal(asset, amount, toAddress, accessToken)
        : await createFiatWithdrawal(amount, bankAccount, bankRouting, accessToken)
      setCreated(result)
      setWithdrawalId(result.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Withdrawal failed')
    } finally {
      setLoading(false)
    }
  }

  const handleCancel = async () => {
    if (!withdrawalId) return
    try {
      await cancelWithdrawalById(withdrawalId, accessToken)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Cannot cancel')
    }
  }

  return (
    <div className="max-w-lg mx-auto p-6 space-y-6">
      <h1 className="text-2xl font-semibold text-text-primary">Withdraw Funds</h1>

      <div className="flex gap-2 border-b border-border">
        {(['CRYPTO', 'FIAT'] as Tab[]).map((t) => (
          <button key={t} onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              tab === t ? 'border-b-2 border-accent text-accent' : 'text-text-secondary hover:text-text-primary'
            }`}>
            {t === 'CRYPTO' ? 'Crypto' : 'Bank Transfer'}
          </button>
        ))}
      </div>

      {!created ? (
        <form onSubmit={handleSubmit} className="space-y-4">
          {tab === 'CRYPTO' && (
            <>
              <div>
                <label className="block text-sm text-text-secondary mb-1">Asset</label>
                <select value={asset} onChange={(e) => setAsset(e.target.value as Asset)}
                  className="w-full bg-bg-secondary border border-border rounded-lg px-3 py-2 text-text-primary">
                  <option value="ETH">ETH (max 10)</option>
                  <option value="BTC">BTC (max 1)</option>
                  <option value="USDT">USDT (max 50,000)</option>
                </select>
              </div>
              <div>
                <label className="block text-sm text-text-secondary mb-1">Destination Address</label>
                <input type="text" value={toAddress} onChange={(e) => setToAddress(e.target.value)}
                  required placeholder="0x... or bc1q..."
                  className="w-full bg-bg-secondary border border-border rounded-lg px-3 py-2 text-text-primary font-mono text-sm" />
              </div>
            </>
          )}

          {tab === 'FIAT' && (
            <>
              <div>
                <label className="block text-sm text-text-secondary mb-1">Bank Account Number</label>
                <input type="text" value={bankAccount} onChange={(e) => setBankAccount(e.target.value)}
                  required placeholder="Account number"
                  className="w-full bg-bg-secondary border border-border rounded-lg px-3 py-2 text-text-primary" />
              </div>
              <div>
                <label className="block text-sm text-text-secondary mb-1">Routing Number</label>
                <input type="text" value={bankRouting} onChange={(e) => setBankRouting(e.target.value)}
                  required placeholder="Routing / sort code"
                  className="w-full bg-bg-secondary border border-border rounded-lg px-3 py-2 text-text-primary" />
              </div>
            </>
          )}

          <div>
            <label className="block text-sm text-text-secondary mb-1">Amount</label>
            <input type="number" value={amount} onChange={(e) => setAmount(e.target.value)}
              step="any" min="0" required placeholder="0.00"
              className="w-full bg-bg-secondary border border-border rounded-lg px-3 py-2 text-text-primary" />
          </div>

          {error && <p className="text-down text-sm">{error}</p>}

          <button type="submit" disabled={loading || !amount}
            className="w-full bg-accent text-white py-2 rounded-lg font-medium hover:opacity-90 disabled:opacity-50 transition-opacity">
            {loading ? 'Submitting…' : 'Submit Withdrawal'}
          </button>
        </form>
      ) : (
        <div className="space-y-4">
          <div className="bg-bg-secondary border border-border rounded-xl p-4 space-y-2">
            <p className="text-sm text-text-secondary">Withdrawal ID</p>
            <p className="font-mono text-xs text-text-primary">{created.id}</p>
            {created.toAddress && (
              <>
                <p className="text-sm text-text-secondary mt-2">To Address</p>
                <p className="font-mono text-sm text-text-primary break-all">{created.toAddress}</p>
              </>
            )}
            <p className="text-sm text-text-secondary mt-2">
              Amount: {created.amount} {created.asset}
            </p>
          </div>

          {(withdrawal ?? created) && (
            <div className="flex items-center justify-between text-sm border border-border rounded-lg px-4 py-3">
              <span className="text-text-secondary">Status</span>
              <span className={`font-semibold ${statusColor((withdrawal ?? created)!.status)}`}>
                {(withdrawal ?? created)!.status}
              </span>
            </div>
          )}

          {withdrawal?.rejectionReason && (
            <p className="text-down text-sm">Reason: {withdrawal.rejectionReason}</p>
          )}

          {(withdrawal?.status ?? created?.status) === 'PENDING' && (
            <button onClick={handleCancel}
              className="text-sm text-down hover:underline">
              Cancel withdrawal
            </button>
          )}

          <button onClick={() => { setCreated(null); setWithdrawalId(null); setAmount('') }}
            className="text-sm text-accent hover:underline block">
            Submit another withdrawal
          </button>
        </div>
      )}
    </div>
  )
}
```

---

## 15. Implementation Checklist

| Step | Files | Acceptance Criteria |
|------|-------|---------------------|
| 1 | `app/models/domain.py`, `migrations/versions/001_initial_schema.py` | Migration runs; `withdrawals` + `withdrawal_audit_log` tables created with idx_withdrawals_aml |
| 2 | `app/repositories/withdrawal_repo.py` | All 6 methods pass; `get_daily_executed_sum` returns 24h rolling sum |
| 3 | `app/services/aml_service.py` | TC-A01–TC-A04 pass; multi-asset USD aggregation works |
| 4 | `app/services/withdrawal_service.py` | TC-W01–TC-W16 pass; FAILED/REJECTED always calls credit endpoint |
| 5 | `infra/step_functions_asl.json`, `infra/step_functions.tf` | State machine deploys; Catch clauses route to RejectWithdrawal/FailWithdrawal |
| 6 | `services/spot-trading/app/routers/internal.py` | `POST /internal/positions/deduct` returns 422 on insufficient balance |
| 7 | `app/main.py`, `app/routers/withdrawals.py`, `app/schemas.py`, `app/middleware/auth.py` | 5 endpoints return correct HTTP codes; DELETE /withdrawals/{id} returns 409 on non-PENDING |
| 8 | `app/producers/eventbridge_producer.py` | Event published to `finance-events` with source=`finance.withdrawal` |
| 9 | `infra/ecs.tf`, `infra/eventbridge.tf`, `infra/iam.tf`, `infra/variables.tf` | `terraform plan` shows no errors |
| 10 | `tests/` | TC-W01–W16 + TC-A01–A04 pass (20 tests total) |
| 11a | `apps/web/src/services/financeApi.ts` | 4 new functions added alongside existing |
| 11b | `apps/web/src/hooks/useWithdrawal.ts` | Polls every 10s, stops on terminal status |
| 11c | `apps/web/src/app/(app)/withdraw/page.tsx` | Cancel button visible in PENDING; rejection reason displayed |
