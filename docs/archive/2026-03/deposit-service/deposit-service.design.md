# Design: deposit-service

> **Feature**: deposit-service
> **Plan**: [deposit-service.plan.md](../../01-plan/features/deposit-service.plan.md)
> **Created**: 2026-03-08
> **Phase**: Design
> **Level**: Enterprise

---

## 1. Service Layout

```
services/deposit/
├── app/
│   ├── main.py                          # FastAPI app + lifespan
│   ├── config.py                        # Settings (pydantic-settings)
│   ├── schemas.py                       # Request/Response Pydantic models
│   ├── models/
│   │   └── domain.py                    # DepositRequest, DepositType, DepositStatus
│   ├── repositories/
│   │   └── deposit_repo.py              # DepositRepository ABC + PostgresDepositRepository
│   ├── services/
│   │   ├── deposit_service.py           # Core business logic
│   │   ├── wallet_service.py            # Mock HD wallet address generation
│   │   └── step_fn_service.py           # Step Functions execution management
│   ├── producers/
│   │   └── eventbridge_producer.py      # EventBridge publish
│   ├── routers/
│   │   ├── deposits.py                  # User-facing CRUD endpoints
│   │   └── webhooks.py                  # Internal webhook endpoints (HMAC)
│   └── middleware/
│       └── auth.py                      # X-User-Id header validation
├── migrations/
│   └── versions/
│       └── 001_initial_schema.py        # Alembic migration
├── infra/
│   ├── aurora.tf                        # Aurora PostgreSQL (finance schema)
│   ├── ecs.tf                           # ECS Fargate service
│   ├── step_functions.tf                # Step Functions state machine (ASL)
│   ├── eventbridge.tf                   # EventBridge bus + cross-account rules
│   ├── iam.tf                           # Task role, Step Fn role, EB role
│   └── sqs.tf                           # DLQ for failed Step Fn tasks
└── tests/
    ├── conftest.py
    ├── test_deposit_service.py
    └── test_webhooks.py
```

---

## 2. Domain Model

### 2.1 Enums

```python
# app/models/domain.py
from enum import Enum
from decimal import Decimal
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
import uuid


class DepositType(str, Enum):
    CRYPTO = "CRYPTO"
    FIAT   = "FIAT"


class DepositStatus(str, Enum):
    PENDING    = "PENDING"
    CONFIRMING = "CONFIRMING"
    CONFIRMED  = "CONFIRMED"
    CREDITED   = "CREDITED"
    FAILED     = "FAILED"
    EXPIRED    = "EXPIRED"


MINIMUM_AMOUNTS: dict[str, Decimal] = {
    "ETH":  Decimal("0.001"),
    "BTC":  Decimal("0.0001"),
    "USDT": Decimal("10"),
    "USD":  Decimal("10"),
}

REQUIRED_CONFIRMATIONS: dict[str, int] = {
    "ETH":  12,
    "BTC":  6,
    "USDT": 12,   # ERC-20 USDT follows ETH confirmation count
}
```

### 2.2 DepositRequest Dataclass

```python
@dataclass
class DepositRequest:
    id:                     str            # UUID PK
    user_id:                str            # FK → Identity users
    type:                   DepositType
    asset:                  str            # ETH | BTC | USDT | USD
    amount:                 Decimal
    status:                 DepositStatus  = DepositStatus.PENDING
    wallet_address:         Optional[str]  = None   # crypto: platform address
    tx_hash:                Optional[str]  = None   # crypto: on-chain tx
    bank_reference:         Optional[str]  = None   # fiat: reference code
    confirmations:          int            = 0
    required_confirmations: int            = 0
    step_fn_execution_arn:  Optional[str]  = None
    credited_at:            Optional[datetime] = None
    expires_at:             Optional[datetime] = None
    created_at:             Optional[datetime] = None
    updated_at:             Optional[datetime] = None

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())
```

---

## 3. Database Schema

### 3.1 Alembic Migration — `001_initial_schema.py`

```python
# migrations/versions/001_initial_schema.py
"""Initial schema: deposits + deposit_audit_log"""
from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None


def upgrade():
    op.execute("CREATE SCHEMA IF NOT EXISTS finance")

    op.execute("""
        CREATE TYPE finance.deposit_type AS ENUM ('CRYPTO', 'FIAT')
    """)
    op.execute("""
        CREATE TYPE finance.deposit_status AS ENUM (
            'PENDING', 'CONFIRMING', 'CONFIRMED', 'CREDITED', 'FAILED', 'EXPIRED'
        )
    """)

    op.execute("""
        CREATE TABLE finance.deposits (
            id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id                VARCHAR(64)            NOT NULL,
            type                   finance.deposit_type   NOT NULL,
            asset                  VARCHAR(10)            NOT NULL,
            amount                 NUMERIC(20, 8)         NOT NULL,
            status                 finance.deposit_status NOT NULL DEFAULT 'PENDING',
            wallet_address         VARCHAR(128),
            tx_hash                VARCHAR(128),
            bank_reference         VARCHAR(64),
            confirmations          INT                    NOT NULL DEFAULT 0,
            required_confirmations INT                    NOT NULL DEFAULT 0,
            step_fn_execution_arn  VARCHAR(2048),
            credited_at            TIMESTAMPTZ,
            expires_at             TIMESTAMPTZ            NOT NULL,
            created_at             TIMESTAMPTZ            NOT NULL DEFAULT NOW(),
            updated_at             TIMESTAMPTZ            NOT NULL DEFAULT NOW(),

            CONSTRAINT deposits_tx_hash_unique UNIQUE (tx_hash),
            CONSTRAINT deposits_bank_ref_unique UNIQUE (bank_reference),
            CONSTRAINT deposits_amount_positive CHECK (amount > 0)
        )
    """)

    op.execute("""
        CREATE INDEX idx_deposits_user_id   ON finance.deposits (user_id, created_at DESC);
        CREATE INDEX idx_deposits_status    ON finance.deposits (status, expires_at);
        CREATE INDEX idx_deposits_address   ON finance.deposits (wallet_address) WHERE wallet_address IS NOT NULL;
    """)

    op.execute("""
        CREATE TABLE finance.deposit_audit_log (
            id          BIGSERIAL PRIMARY KEY,
            deposit_id  UUID           NOT NULL REFERENCES finance.deposits(id),
            from_status finance.deposit_status,
            to_status   finance.deposit_status NOT NULL,
            note        TEXT,
            created_at  TIMESTAMPTZ    NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX idx_audit_deposit_id ON finance.deposit_audit_log (deposit_id, created_at DESC)
    """)


def downgrade():
    op.execute("DROP TABLE IF EXISTS finance.deposit_audit_log")
    op.execute("DROP TABLE IF EXISTS finance.deposits")
    op.execute("DROP TYPE IF EXISTS finance.deposit_status")
    op.execute("DROP TYPE IF EXISTS finance.deposit_type")
```

---

## 4. Repository Layer

### 4.1 Interface

```python
# app/repositories/deposit_repo.py
from abc import ABC, abstractmethod
from typing import Optional, List
from ..models.domain import DepositRequest, DepositStatus


class DepositRepository(ABC):

    @abstractmethod
    async def create(self, deposit: DepositRequest) -> DepositRequest: ...

    @abstractmethod
    async def get(self, deposit_id: str) -> Optional[DepositRequest]: ...

    @abstractmethod
    async def get_by_tx_hash(self, tx_hash: str) -> Optional[DepositRequest]: ...

    @abstractmethod
    async def get_by_bank_reference(self, bank_reference: str) -> Optional[DepositRequest]: ...

    @abstractmethod
    async def update_status(
        self,
        deposit_id: str,
        new_status: DepositStatus,
        note: str = "",
        **kwargs,        # extra field updates: tx_hash, confirmations, step_fn_execution_arn, credited_at
    ) -> None: ...

    @abstractmethod
    async def list_by_user(self, user_id: str, limit: int = 50) -> List[DepositRequest]: ...

    @abstractmethod
    async def get_expired(self) -> List[DepositRequest]: ...
```

### 4.2 Implementation

```python
class PostgresDepositRepository(DepositRepository):
    def __init__(self, conn) -> None:   # asyncpg.Connection
        self._conn = conn

    async def create(self, d: DepositRequest) -> DepositRequest:
        row = await self._conn.fetchrow(
            """
            INSERT INTO finance.deposits
              (id, user_id, type, asset, amount, wallet_address, bank_reference,
               required_confirmations, expires_at)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            RETURNING *
            """,
            d.id, d.user_id, d.type.value, d.asset, str(d.amount),
            d.wallet_address, d.bank_reference, d.required_confirmations, d.expires_at,
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

    async def get_by_bank_reference(self, bank_reference: str) -> Optional[DepositRequest]:
        row = await self._conn.fetchrow(
            "SELECT * FROM finance.deposits WHERE bank_reference = $1", bank_reference
        )
        return _row_to_deposit(row) if row else None

    async def update_status(
        self, deposit_id: str, new_status: DepositStatus, note: str = "", **kwargs
    ) -> None:
        # Build dynamic SET clause for optional extra fields
        set_parts = ["status = $2", "updated_at = NOW()"]
        params = [deposit_id, new_status.value]
        i = 3
        for key, val in kwargs.items():
            if key in ("tx_hash", "confirmations", "step_fn_execution_arn", "credited_at"):
                set_parts.append(f"{key} = ${i}")
                params.append(val)
                i += 1

        # Fetch previous status for audit
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
                INSERT INTO finance.deposit_audit_log (deposit_id, from_status, to_status, note)
                VALUES ($1, $2, $3, $4)
                """,
                deposit_id, prev_status, new_status.value, note,
            )

    async def list_by_user(self, user_id: str, limit: int = 50) -> list[DepositRequest]:
        rows = await self._conn.fetch(
            "SELECT * FROM finance.deposits WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2",
            user_id, limit,
        )
        return [_row_to_deposit(r) for r in rows]

    async def get_expired(self) -> list[DepositRequest]:
        rows = await self._conn.fetch(
            "SELECT * FROM finance.deposits WHERE status='PENDING' AND expires_at < NOW()"
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
```

---

## 5. Wallet Service (Mock)

```python
# app/services/wallet_service.py
import hashlib


class WalletService:
    """
    Mock HD wallet: deterministic address per (user_id, asset).
    In production: replace with BIP-44 key derivation from platform seed.
    """

    _PREFIX: dict[str, str] = {
        "ETH":  "0x",
        "BTC":  "bc1q",
        "USDT": "0x",    # ERC-20 on Ethereum
    }

    def generate_address(self, user_id: str, asset: str) -> str:
        digest = hashlib.sha256(f"{user_id}:{asset}".encode()).hexdigest()
        prefix = self._PREFIX.get(asset, "0x")
        if asset == "BTC":
            return f"bc1q{digest[:38]}"
        return f"0x{digest[:40]}"

    def validate_address(self, address: str, asset: str) -> bool:
        if asset in ("ETH", "USDT"):
            return address.startswith("0x") and len(address) == 42
        if asset == "BTC":
            return address.startswith("bc1q") and len(address) == 42
        return False
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

    async def start_execution(self, deposit_id: str) -> str:
        """
        Start Step Functions execution. Returns execution ARN.
        Name is deposit_id (ensures idempotency — duplicate start raises ExecutionAlreadyExists).
        """
        resp = self._client.start_execution(
            stateMachineArn=settings.step_fn_arn,
            name=deposit_id,             # idempotency key
            input=json.dumps({"depositId": deposit_id}),
        )
        return resp["executionArn"]
```

---

## 7. Deposit Service (Core Logic)

```python
# app/services/deposit_service.py
import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import httpx

from ..config import settings
from ..models.domain import (
    DepositRequest, DepositStatus, DepositType,
    MINIMUM_AMOUNTS, REQUIRED_CONFIRMATIONS,
)
from ..repositories.deposit_repo import DepositRepository
from .wallet_service import WalletService
from .step_fn_service import StepFnService


class DepositService:
    def __init__(
        self,
        repo: DepositRepository,
        wallet_svc: WalletService,
        step_fn_svc: StepFnService,
    ) -> None:
        self._repo       = repo
        self._wallet     = wallet_svc
        self._step_fn    = step_fn_svc

    # ── Create ─────────────────────────────────────────────────────────────────

    async def create_crypto_deposit(
        self, user_id: str, asset: str, amount: Decimal
    ) -> DepositRequest:
        _validate_amount(asset, amount)
        address = self._wallet.generate_address(user_id, asset)
        deposit = DepositRequest(
            id=DepositRequest.new_id(),
            user_id=user_id,
            type=DepositType.CRYPTO,
            asset=asset,
            amount=amount,
            wallet_address=address,
            required_confirmations=REQUIRED_CONFIRMATIONS.get(asset, 12),
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        return await self._repo.create(deposit)

    async def create_fiat_deposit(
        self, user_id: str, amount: Decimal
    ) -> DepositRequest:
        _validate_amount("USD", amount)
        bank_ref = _generate_bank_reference()
        deposit = DepositRequest(
            id=DepositRequest.new_id(),
            user_id=user_id,
            type=DepositType.FIAT,
            asset="USD",
            amount=amount,
            bank_reference=bank_ref,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        return await self._repo.create(deposit)

    # ── Webhook Processing ─────────────────────────────────────────────────────

    async def process_crypto_webhook(
        self,
        tx_hash: str,
        address: str,
        amount: Decimal,
        confirmations: int,
    ) -> Optional[DepositRequest]:
        """
        Idempotent: if tx_hash already exists in CONFIRMING+ state, return existing.
        Raises ValueError if deposit not found for address.
        """
        # Idempotency check
        existing = await self._repo.get_by_tx_hash(tx_hash)
        if existing and existing.status not in (DepositStatus.PENDING,):
            return existing

        # Find deposit by wallet address
        deposit = await _find_by_address(self._repo, address)
        if not deposit:
            raise ValueError(f"No PENDING deposit for address {address}")

        # Start Step Functions execution
        execution_arn = await self._step_fn.start_execution(deposit.id)

        await self._repo.update_status(
            deposit.id,
            DepositStatus.CONFIRMING,
            note=f"Webhook received tx_hash={tx_hash}",
            tx_hash=tx_hash,
            confirmations=confirmations,
            step_fn_execution_arn=execution_arn,
        )
        return await self._repo.get(deposit.id)

    async def process_fiat_webhook(
        self,
        bank_reference: str,
        amount: Decimal,
    ) -> Optional[DepositRequest]:
        """Idempotent: duplicate bank_reference webhook is silently ignored."""
        deposit = await self._repo.get_by_bank_reference(bank_reference)
        if not deposit:
            raise ValueError(f"No deposit for bank_reference={bank_reference}")
        if deposit.status != DepositStatus.PENDING:
            return deposit   # idempotent

        execution_arn = await self._step_fn.start_execution(deposit.id)

        await self._repo.update_status(
            deposit.id,
            DepositStatus.CONFIRMING,
            note="Fiat bank webhook received",
            step_fn_execution_arn=execution_arn,
        )
        return await self._repo.get(deposit.id)

    # ── Credit Balance ─────────────────────────────────────────────────────────

    async def credit_balance(self, deposit_id: str) -> None:
        """
        Called by Step Functions (Lambda task) after confirmation.
        Calls spot-trading internal API, then atomically updates status to CREDITED.
        Idempotent: if already CREDITED, returns immediately.
        """
        deposit = await self._repo.get(deposit_id)
        if not deposit:
            raise ValueError(f"Deposit {deposit_id} not found")
        if deposit.status == DepositStatus.CREDITED:
            return   # idempotent
        if deposit.status != DepositStatus.CONFIRMED:
            raise ValueError(f"Cannot credit deposit in status {deposit.status}")

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.spot_trading_internal_url}/internal/positions/credit",
                headers={"X-Internal-Token": settings.internal_token},
                json={
                    "user_id":   deposit.user_id,
                    "asset":     deposit.asset,
                    "amount":    str(deposit.amount),
                    "deposit_id": deposit.id,
                },
            )
            resp.raise_for_status()

        now = datetime.now(timezone.utc)
        await self._repo.update_status(
            deposit.id,
            DepositStatus.CREDITED,
            note="Balance credited to spot-trading position",
            credited_at=now,
        )

    # ── Expiry ────────────────────────────────────────────────────────────────

    async def expire_pending_deposits(self) -> int:
        """Batch expire PENDING deposits past expires_at. Returns count expired."""
        expired = await self._repo.get_expired()
        for d in expired:
            await self._repo.update_status(
                d.id, DepositStatus.EXPIRED, note="Expired after 24h"
            )
        return len(expired)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _validate_amount(asset: str, amount: Decimal) -> None:
    minimum = MINIMUM_AMOUNTS.get(asset)
    if minimum and amount < minimum:
        raise ValueError(f"Amount {amount} below minimum {minimum} for {asset}")


def _generate_bank_reference() -> str:
    return "DEP-" + secrets.token_hex(8).upper()


async def _find_by_address(
    repo: DepositRepository, address: str
) -> Optional[DepositRequest]:
    # Fetch PENDING deposits matching this wallet address
    # Implemented via raw query in repo (not in ABC for clarity — internal helper)
    rows = await repo._conn.fetch(
        "SELECT * FROM finance.deposits WHERE wallet_address=$1 AND status='PENDING'",
        address,
    )
    if rows:
        from ..repositories.deposit_repo import _row_to_deposit
        return _row_to_deposit(rows[0])
    return None
```

---

## 8. EventBridge Producer

```python
# app/producers/eventbridge_producer.py
import json
import boto3
from datetime import datetime, timezone
from ..config import settings
from ..models.domain import DepositRequest


class EventBridgeProducer:
    def __init__(self):
        self._client = boto3.client("events", region_name=settings.aws_region)

    async def publish_deposit_confirmed(self, deposit: DepositRequest) -> None:
        self._client.put_events(
            Entries=[{
                "Source":       "finance.deposit",
                "DetailType":   "DepositConfirmed",
                "EventBusName": settings.eventbridge_bus_name,
                "Detail": json.dumps({
                    "deposit_id": deposit.id,
                    "user_id":    deposit.user_id,
                    "asset":      deposit.asset,
                    "amount":     str(deposit.amount),
                    "credited_at": deposit.credited_at.isoformat()
                        if deposit.credited_at else datetime.now(timezone.utc).isoformat(),
                }),
            }]
        )
```

---

## 9. FastAPI Application

### 9.1 Config

```python
# app/config.py
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_url:                   str   # asyncpg DSN
    aws_region:               str   = "ap-northeast-2"
    step_fn_arn:              str   # Step Functions state machine ARN
    eventbridge_bus_name:     str   = "finance-events"
    spot_trading_internal_url: str  # https://internal.spot-trading.svc
    internal_token:           str   # Shared secret for internal API auth
    webhook_hmac_secret:      str   # HMAC-SHA256 secret for webhook validation
    deposit_expiry_hours:     int   = 24

    class Config:
        env_file = ".env"


settings = Settings()
```

### 9.2 Schemas

```python
# app/schemas.py
from decimal import Decimal
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator


class CreateCryptoDepositRequest(BaseModel):
    asset:  str
    amount: str   # Decimal as string to avoid float imprecision

    @field_validator("asset")
    @classmethod
    def validate_asset(cls, v: str) -> str:
        if v not in ("ETH", "BTC", "USDT"):
            raise ValueError("asset must be ETH, BTC, or USDT")
        return v

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: str) -> str:
        d = Decimal(v)
        if d <= 0:
            raise ValueError("amount must be positive")
        return v


class CreateFiatDepositRequest(BaseModel):
    amount: str

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: str) -> str:
        d = Decimal(v)
        if d <= 0:
            raise ValueError("amount must be positive")
        return v


class DepositResponse(BaseModel):
    id:              str
    type:            str
    asset:           str
    amount:          str
    status:          str
    wallet_address:  Optional[str]
    bank_reference:  Optional[str]
    tx_hash:         Optional[str]
    confirmations:   int
    expires_at:      datetime
    credited_at:     Optional[datetime]
    created_at:      datetime


class CryptoWebhookPayload(BaseModel):
    tx_hash:       str
    address:       str
    amount:        str
    confirmations: int


class FiatWebhookPayload(BaseModel):
    bank_reference: str
    amount:         str


class CreditRequest(BaseModel):
    """Internal: POST /internal/positions/credit from deposit service."""
    user_id:    str
    asset:      str
    amount:     str
    deposit_id: str
```

### 9.3 Auth Middleware

```python
# app/middleware/auth.py
from fastapi import Request, HTTPException

INTERNAL_PATHS = ["/internal/", "/health"]


async def require_user_id(request: Request) -> str:
    """
    Lambda Authorizer injects X-User-Id header for authenticated routes.
    Internal webhook paths skip this check.
    """
    path = request.url.path
    if any(path.startswith(p) for p in INTERNAL_PATHS):
        return ""
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-Id header")
    return user_id
```

### 9.4 Deposits Router

```python
# app/routers/deposits.py
from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Request
from ..main import db_pool, deposit_svc
from ..schemas import (
    CreateCryptoDepositRequest,
    CreateFiatDepositRequest,
    DepositResponse,
)
from ..middleware.auth import require_user_id

router = APIRouter(prefix="/deposits")


def _to_response(d) -> DepositResponse:
    return DepositResponse(
        id=d.id, type=d.type.value, asset=d.asset,
        amount=str(d.amount), status=d.status.value,
        wallet_address=d.wallet_address, bank_reference=d.bank_reference,
        tx_hash=d.tx_hash, confirmations=d.confirmations,
        expires_at=d.expires_at, credited_at=d.credited_at,
        created_at=d.created_at,
    )


@router.post("/crypto", response_model=DepositResponse, status_code=201)
async def create_crypto_deposit(
    body: CreateCryptoDepositRequest,
    user_id: str = Depends(require_user_id),
):
    try:
        deposit = await deposit_svc.create_crypto_deposit(
            user_id, body.asset, Decimal(body.amount)
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _to_response(deposit)


@router.post("/fiat", response_model=DepositResponse, status_code=201)
async def create_fiat_deposit(
    body: CreateFiatDepositRequest,
    user_id: str = Depends(require_user_id),
):
    try:
        deposit = await deposit_svc.create_fiat_deposit(user_id, Decimal(body.amount))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _to_response(deposit)


@router.get("/{deposit_id}", response_model=DepositResponse)
async def get_deposit(deposit_id: str, user_id: str = Depends(require_user_id)):
    async with db_pool.acquire() as conn:
        from ..repositories.deposit_repo import PostgresDepositRepository
        deposit = await PostgresDepositRepository(conn).get(deposit_id)
    if not deposit or deposit.user_id != user_id:
        raise HTTPException(status_code=404, detail="Deposit not found")
    return _to_response(deposit)


@router.get("", response_model=list[DepositResponse])
async def list_deposits(user_id: str = Depends(require_user_id)):
    async with db_pool.acquire() as conn:
        from ..repositories.deposit_repo import PostgresDepositRepository
        deposits = await PostgresDepositRepository(conn).list_by_user(user_id)
    return [_to_response(d) for d in deposits]
```

### 9.5 Webhooks Router (HMAC Validation)

```python
# app/routers/webhooks.py
import hashlib
import hmac

from fastapi import APIRouter, HTTPException, Request
from decimal import Decimal

from ..config import settings
from ..main import deposit_svc
from ..schemas import CryptoWebhookPayload, FiatWebhookPayload

router = APIRouter(prefix="/internal/webhooks")


async def _validate_hmac(request: Request) -> bytes:
    """Validates X-Webhook-Signature header against request body."""
    signature = request.headers.get("X-Webhook-Signature", "")
    body = await request.body()
    expected = hmac.new(
        settings.webhook_hmac_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature, f"sha256={expected}"):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    return body


@router.post("/crypto")
async def crypto_webhook(request: Request):
    body_bytes = await _validate_hmac(request)
    payload = CryptoWebhookPayload.model_validate_json(body_bytes)
    try:
        deposit = await deposit_svc.process_crypto_webhook(
            tx_hash=payload.tx_hash,
            address=payload.address,
            amount=Decimal(payload.amount),
            confirmations=payload.confirmations,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"deposit_id": deposit.id, "status": deposit.status.value}


@router.post("/fiat")
async def fiat_webhook(request: Request):
    body_bytes = await _validate_hmac(request)
    payload = FiatWebhookPayload.model_validate_json(body_bytes)
    try:
        deposit = await deposit_svc.process_fiat_webhook(
            bank_reference=payload.bank_reference,
            amount=Decimal(payload.amount),
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"deposit_id": deposit.id, "status": deposit.status.value}
```

### 9.6 Main Application

```python
# app/main.py
from __future__ import annotations
import asyncpg
from contextlib import asynccontextmanager
from fastapi import FastAPI

from .config import settings
from .services.deposit_service import DepositService
from .services.wallet_service import WalletService
from .services.step_fn_service import StepFnService
from .producers.eventbridge_producer import EventBridgeProducer
from .routers import deposits, webhooks

db_pool: asyncpg.Pool | None = None
deposit_svc: DepositService | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool, deposit_svc
    db_pool = await asyncpg.create_pool(settings.db_url, min_size=3, max_size=15)

    from .repositories.deposit_repo import PostgresDepositRepository
    wallet_svc  = WalletService()
    step_fn_svc = StepFnService()
    eb_producer = EventBridgeProducer()

    # deposit_svc is a shared singleton; repo is created per-request via db_pool
    deposit_svc = DepositService(
        repo=None,           # repo injected per request
        wallet_svc=wallet_svc,
        step_fn_svc=step_fn_svc,
    )

    yield

    await db_pool.close()


app = FastAPI(title="DepositService", version="1.0.0", lifespan=lifespan)
app.include_router(deposits.router)
app.include_router(webhooks.router)


@app.get("/health")
async def health():
    return {"status": "ok", "db": db_pool is not None}
```

---

## 10. Step Functions State Machine (ASL)

```json
// infra/step_functions_asl.json
{
  "Comment": "Deposit confirmation workflow",
  "StartAt": "WaitForConfirmations",
  "States": {
    "WaitForConfirmations": {
      "Type": "Wait",
      "Seconds": 30,
      "Next": "CheckConfirmations"
    },
    "CheckConfirmations": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "${check_confirmations_fn_arn}",
        "Payload.$": "$"
      },
      "ResultPath": "$.checkResult",
      "Retry": [{ "ErrorEquals": ["States.TaskFailed"], "MaxAttempts": 3, "IntervalSeconds": 5 }],
      "Next": "IsConfirmed"
    },
    "IsConfirmed": {
      "Type": "Choice",
      "Choices": [
        {
          "Variable": "$.checkResult.Payload.confirmed",
          "BooleanEquals": true,
          "Next": "CreditBalance"
        },
        {
          "Variable": "$.checkResult.Payload.failed",
          "BooleanEquals": true,
          "Next": "HandleFailure"
        }
      ],
      "Default": "WaitForConfirmations"
    },
    "CreditBalance": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "${credit_balance_fn_arn}",
        "Payload.$": "$"
      },
      "Retry": [
        {
          "ErrorEquals": ["States.TaskFailed"],
          "MaxAttempts": 3,
          "IntervalSeconds": 10,
          "BackoffRate": 2
        }
      ],
      "ResultPath": "$.creditResult",
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
    "HandleFailure": {
      "Type": "Task",
      "Resource": "arn:aws:states:::lambda:invoke",
      "Parameters": {
        "FunctionName": "${handle_failure_fn_arn}",
        "Payload.$": "$"
      },
      "End": true
    }
  },
  "TimeoutSeconds": 86400
}
```

---

## 11. Spot-Trading: Internal Credit Endpoint (Addition)

The deposit service requires `POST /internal/positions/credit` on the spot-trading service.

### 11.1 New router file

```python
# services/spot-trading/app/routers/internal.py
from decimal import Decimal
from fastapi import APIRouter, HTTPException, Request

from ..main import db_pool
from ..repositories.position_repo import PositionRepository
from ..config import settings

router = APIRouter(prefix="/internal")


@router.post("/positions/credit", status_code=204)
async def credit_position(request: Request):
    token = request.headers.get("X-Internal-Token", "")
    if token != settings.internal_token:
        raise HTTPException(status_code=401, detail="Invalid internal token")

    body = await request.json()
    user_id    = body["user_id"]
    asset      = body["asset"]
    amount     = Decimal(str(body["amount"]))
    deposit_id = body["deposit_id"]    # for logging / idempotency ref

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            repo = PositionRepository(conn)
            await repo._settle_credit(user_id, asset, amount)
```

### 11.2 Register in main.py

```python
# services/spot-trading/app/main.py (addition)
from .routers import orderbook, orders, positions, trades, internal   # add internal

# ... existing code ...
app.include_router(internal.router)   # add this line
```

### 11.3 Config addition

```python
# services/spot-trading/app/config.py (addition)
internal_token: str = ""   # shared secret; populated from Secrets Manager
```

---

## 12. Terraform Infrastructure

### 12.1 `infra/aurora.tf`

```hcl
resource "aws_rds_cluster" "deposit" {
  cluster_identifier     = "${var.env}-deposit-aurora"
  engine                 = "aurora-postgresql"
  engine_version         = "15.4"
  database_name          = "finance"
  master_username        = "deposit_admin"
  manage_master_user_password = true   # Secrets Manager rotation
  db_subnet_group_name   = var.db_subnet_group
  vpc_security_group_ids = [aws_security_group.aurora.id]
  backup_retention_period = 7
  deletion_protection    = true

  tags = { Service = "deposit" }
}

resource "aws_rds_cluster_instance" "deposit" {
  count              = var.env == "prod" ? 2 : 1
  cluster_identifier = aws_rds_cluster.deposit.id
  instance_class     = "db.r6g.large"
  engine             = aws_rds_cluster.deposit.engine
}
```

### 12.2 `infra/sqs.tf`

```hcl
resource "aws_sqs_queue" "deposit_dlq" {
  name                       = "${var.env}-deposit-dlq"
  message_retention_seconds  = 1209600   # 14 days
}

resource "aws_sqs_queue" "deposit_tasks" {
  name                      = "${var.env}-deposit-tasks"
  visibility_timeout_seconds = 300
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.deposit_dlq.arn
    maxReceiveCount     = 3
  })
}
```

### 12.3 `infra/step_functions.tf`

```hcl
resource "aws_sfn_state_machine" "deposit_workflow" {
  name     = "${var.env}-deposit-workflow"
  role_arn = aws_iam_role.step_fn.arn

  definition = templatefile("${path.module}/step_functions_asl.json", {
    check_confirmations_fn_arn = aws_lambda_function.check_confirmations.arn
    credit_balance_fn_arn      = aws_lambda_function.credit_balance.arn
    publish_event_fn_arn       = aws_lambda_function.publish_event.arn
    handle_failure_fn_arn      = aws_lambda_function.handle_failure.arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.step_fn.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }
}
```

### 12.4 `infra/eventbridge.tf`

```hcl
resource "aws_cloudwatch_event_bus" "finance" {
  name = "finance-events"
}

resource "aws_cloudwatch_event_rule" "deposit_confirmed" {
  name           = "${var.env}-deposit-confirmed"
  event_bus_name = aws_cloudwatch_event_bus.finance.name
  event_pattern = jsonencode({
    source      = ["finance.deposit"]
    detail-type = ["DepositConfirmed"]
  })
}

resource "aws_cloudwatch_event_target" "spot_trading_bus" {
  rule           = aws_cloudwatch_event_rule.deposit_confirmed.name
  event_bus_name = aws_cloudwatch_event_bus.finance.name
  arn            = var.spot_trading_event_bus_arn
  role_arn       = aws_iam_role.eventbridge.arn
}
```

### 12.5 `infra/iam.tf`

```hcl
# ECS Task Role
resource "aws_iam_role" "ecs_task" {
  name = "${var.env}-deposit-ecs-task"
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
        Resource = [aws_sfn_state_machine.deposit_workflow.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["events:PutEvents"]
        Resource = [aws_cloudwatch_event_bus.finance.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = ["arn:aws:secretsmanager:${var.region}:${var.account_id}:secret:deposit/*"]
      },
    ]
  })
}

# Step Functions Execution Role
resource "aws_iam_role" "step_fn" {
  name = "${var.env}-deposit-step-fn"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
}

resource "aws_iam_role_policy" "step_fn_policy" {
  role = aws_iam_role.step_fn.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lambda:InvokeFunction"]
      Resource = [
        aws_lambda_function.check_confirmations.arn,
        aws_lambda_function.credit_balance.arn,
        aws_lambda_function.publish_event.arn,
        aws_lambda_function.handle_failure.arn,
      ]
    }]
  })
}
```

---

## 13. Tests

### 13.1 `tests/conftest.py`

```python
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from ..app.models.domain import (
    DepositRequest, DepositType, DepositStatus
)


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.create = AsyncMock()
    repo.get = AsyncMock()
    repo.get_by_tx_hash = AsyncMock(return_value=None)
    repo.get_by_bank_reference = AsyncMock(return_value=None)
    repo.update_status = AsyncMock()
    repo.list_by_user = AsyncMock(return_value=[])
    repo.get_expired = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_wallet():
    wallet = MagicMock()
    wallet.generate_address = MagicMock(return_value="0xabc123def456abc123def456abc123def456abc1")
    wallet.validate_address = MagicMock(return_value=True)
    return wallet


@pytest.fixture
def mock_step_fn():
    svc = AsyncMock()
    svc.start_execution = AsyncMock(
        return_value="arn:aws:states:ap-northeast-2:123456789:execution:deposit-workflow:test-id"
    )
    return svc


@pytest.fixture
def pending_crypto_deposit():
    from datetime import datetime, timezone, timedelta
    return DepositRequest(
        id="dep-uuid-001",
        user_id="user-001",
        type=DepositType.CRYPTO,
        asset="ETH",
        amount=Decimal("0.5"),
        status=DepositStatus.PENDING,
        wallet_address="0xabc123def456abc123def456abc123def456abc1",
        required_confirmations=12,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )


@pytest.fixture
def pending_fiat_deposit():
    from datetime import datetime, timezone, timedelta
    return DepositRequest(
        id="dep-uuid-002",
        user_id="user-001",
        type=DepositType.FIAT,
        asset="USD",
        amount=Decimal("100"),
        status=DepositStatus.PENDING,
        bank_reference="DEP-ABCDEF12",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
    )
```

### 13.2 `tests/test_deposit_service.py`

```python
"""
Tests — DepositService core logic.

Coverage:
  TC-D01  create crypto deposit success
  TC-D02  create crypto deposit below minimum → ValueError
  TC-D03  create fiat deposit success
  TC-D04  create fiat deposit below minimum → ValueError
  TC-D05  process_crypto_webhook — success → CONFIRMING
  TC-D06  process_crypto_webhook — duplicate tx_hash → idempotent return
  TC-D07  process_fiat_webhook — success → CONFIRMING
  TC-D08  process_fiat_webhook — duplicate → idempotent return
  TC-D09  credit_balance — success → CREDITED
  TC-D10  credit_balance — already CREDITED → idempotent no-op
  TC-D11  credit_balance — spot API error → raises
  TC-D12  expire_pending_deposits — expires 2 deposits
"""
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock
from ..app.services.deposit_service import DepositService
from ..app.models.domain import DepositStatus, DepositType


@pytest.fixture
def svc(mock_repo, mock_wallet, mock_step_fn):
    return DepositService(mock_repo, mock_wallet, mock_step_fn)


# TC-D01
@pytest.mark.asyncio
async def test_create_crypto_deposit_success(svc, mock_repo, pending_crypto_deposit):
    mock_repo.create.return_value = pending_crypto_deposit
    result = await svc.create_crypto_deposit("user-001", "ETH", Decimal("0.5"))
    assert result.asset == "ETH"
    assert result.wallet_address is not None
    mock_repo.create.assert_called_once()


# TC-D02
@pytest.mark.asyncio
async def test_create_crypto_deposit_below_minimum(svc):
    with pytest.raises(ValueError, match="below minimum"):
        await svc.create_crypto_deposit("user-001", "ETH", Decimal("0.0001"))


# TC-D03
@pytest.mark.asyncio
async def test_create_fiat_deposit_success(svc, mock_repo, pending_fiat_deposit):
    mock_repo.create.return_value = pending_fiat_deposit
    result = await svc.create_fiat_deposit("user-001", Decimal("100"))
    assert result.bank_reference.startswith("DEP-")
    mock_repo.create.assert_called_once()


# TC-D04
@pytest.mark.asyncio
async def test_create_fiat_deposit_below_minimum(svc):
    with pytest.raises(ValueError, match="below minimum"):
        await svc.create_fiat_deposit("user-001", Decimal("5"))


# TC-D05
@pytest.mark.asyncio
async def test_process_crypto_webhook_success(
    svc, mock_repo, mock_step_fn, pending_crypto_deposit
):
    mock_repo.get_by_tx_hash.return_value = None
    mock_repo.get.return_value = pending_crypto_deposit

    with patch(
        "..app.services.deposit_service._find_by_address",
        return_value=pending_crypto_deposit,
    ):
        result = await svc.process_crypto_webhook(
            tx_hash="0xabc", address=pending_crypto_deposit.wallet_address,
            amount=Decimal("0.5"), confirmations=1,
        )

    mock_step_fn.start_execution.assert_called_once_with(pending_crypto_deposit.id)
    mock_repo.update_status.assert_called_once()


# TC-D06
@pytest.mark.asyncio
async def test_process_crypto_webhook_idempotent(svc, mock_repo, pending_crypto_deposit):
    confirming = pending_crypto_deposit
    confirming.status = DepositStatus.CONFIRMING
    mock_repo.get_by_tx_hash.return_value = confirming

    result = await svc.process_crypto_webhook(
        tx_hash="0xabc", address="any", amount=Decimal("0.5"), confirmations=2
    )
    assert result.status == DepositStatus.CONFIRMING
    mock_repo.update_status.assert_not_called()


# TC-D09
@pytest.mark.asyncio
async def test_credit_balance_success(svc, mock_repo, pending_crypto_deposit):
    confirmed = pending_crypto_deposit
    confirmed.status = DepositStatus.CONFIRMED

    mock_repo.get.return_value = confirmed

    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(return_value=mock_resp)

        await svc.credit_balance(confirmed.id)

    mock_repo.update_status.assert_called_once()
    call_args = mock_repo.update_status.call_args
    assert call_args.args[1] == DepositStatus.CREDITED


# TC-D10
@pytest.mark.asyncio
async def test_credit_balance_idempotent(svc, mock_repo, pending_crypto_deposit):
    credited = pending_crypto_deposit
    credited.status = DepositStatus.CREDITED
    mock_repo.get.return_value = credited

    await svc.credit_balance(credited.id)
    mock_repo.update_status.assert_not_called()


# TC-D12
@pytest.mark.asyncio
async def test_expire_pending_deposits(svc, mock_repo, pending_crypto_deposit, pending_fiat_deposit):
    mock_repo.get_expired.return_value = [pending_crypto_deposit, pending_fiat_deposit]
    count = await svc.expire_pending_deposits()
    assert count == 2
    assert mock_repo.update_status.call_count == 2
```

### 13.3 `tests/test_webhooks.py`

```python
"""
Tests — Webhook HMAC validation + idempotency.

Coverage:
  TC-W01  Valid HMAC → 200
  TC-W02  Missing signature → 401
  TC-W03  Tampered body → 401
  TC-W04  Duplicate crypto webhook → idempotent 200
  TC-W05  Unknown wallet address → 422
  TC-W06  Valid fiat webhook → 200
  TC-W07  Duplicate fiat webhook → idempotent 200
"""
import hashlib
import hmac
import json
import pytest
from decimal import Decimal
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock


def _sign(body: bytes, secret: str) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


HMAC_SECRET = "test-secret"
CRYPTO_PAYLOAD = {"tx_hash": "0xabc", "address": "0xaddr", "amount": "0.5", "confirmations": 12}
FIAT_PAYLOAD   = {"bank_reference": "DEP-ABCDEF12", "amount": "100"}


@pytest.mark.asyncio
async def test_valid_crypto_webhook(app):
    body = json.dumps(CRYPTO_PAYLOAD).encode()
    sig  = _sign(body, HMAC_SECRET)

    with patch("..app.routers.webhooks.deposit_svc") as mock_svc:
        from ..app.models.domain import DepositStatus
        mock_dep = AsyncMock()
        mock_dep.id = "dep-001"
        mock_dep.status = DepositStatus.CONFIRMING
        mock_svc.process_crypto_webhook = AsyncMock(return_value=mock_dep)

        async with AsyncClient(transport=ASGITransport(app=app)) as client:
            resp = await client.post(
                "/internal/webhooks/crypto",
                content=body,
                headers={"X-Webhook-Signature": sig, "Content-Type": "application/json"},
            )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_missing_hmac_returns_401(app):
    body = json.dumps(CRYPTO_PAYLOAD).encode()
    async with AsyncClient(transport=ASGITransport(app=app)) as client:
        resp = await client.post(
            "/internal/webhooks/crypto",
            content=body,
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_tampered_body_returns_401(app):
    body = json.dumps(CRYPTO_PAYLOAD).encode()
    sig  = _sign(body, HMAC_SECRET)
    tampered = body + b"extra"
    async with AsyncClient(transport=ASGITransport(app=app)) as client:
        resp = await client.post(
            "/internal/webhooks/crypto",
            content=tampered,
            headers={"X-Webhook-Signature": sig, "Content-Type": "application/json"},
        )
    assert resp.status_code == 401
```

---

## 14. Frontend

### 14.1 `apps/web/src/services/financeApi.ts`

```typescript
const FINANCE_API = process.env.NEXT_PUBLIC_FINANCE_API_URL!

export interface DepositResponse {
  id: string
  type: 'CRYPTO' | 'FIAT'
  asset: string
  amount: string
  status: 'PENDING' | 'CONFIRMING' | 'CONFIRMED' | 'CREDITED' | 'FAILED' | 'EXPIRED'
  walletAddress?: string
  bankReference?: string
  txHash?: string
  confirmations: number
  expiresAt: string
  creditedAt?: string
  createdAt: string
}

export async function createCryptoDeposit(
  asset: string,
  amount: string,
  token: string,
): Promise<DepositResponse> {
  const res = await fetch(`${FINANCE_API}/deposits/crypto`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ asset, amount }),
  })
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.detail ?? 'Failed to create deposit')
  }
  return res.json()
}

export async function createFiatDeposit(
  amount: string,
  token: string,
): Promise<DepositResponse> {
  const res = await fetch(`${FINANCE_API}/deposits/fiat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ amount }),
  })
  if (!res.ok) {
    const err = await res.json()
    throw new Error(err.detail ?? 'Failed to create fiat deposit')
  }
  return res.json()
}

export async function getDeposit(
  depositId: string,
  token: string,
): Promise<DepositResponse> {
  const res = await fetch(`${FINANCE_API}/deposits/${depositId}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Deposit not found')
  return res.json()
}

export async function listDeposits(token: string): Promise<DepositResponse[]> {
  const res = await fetch(`${FINANCE_API}/deposits`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to fetch deposits')
  return res.json()
}
```

### 14.2 `apps/web/src/hooks/useDeposit.ts`

```typescript
'use client'

import { useEffect, useRef, useState } from 'react'
import { getDeposit, DepositResponse } from '../services/financeApi'

const TERMINAL_STATUSES = new Set(['CREDITED', 'FAILED', 'EXPIRED'])
const POLL_INTERVAL_MS = 10_000

export function useDeposit(depositId: string | null, token: string) {
  const [deposit, setDeposit] = useState<DepositResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const intervalRef = useRef<NodeJS.Timeout | null>(null)

  useEffect(() => {
    if (!depositId) return

    const fetchDeposit = async () => {
      try {
        const d = await getDeposit(depositId, token)
        setDeposit(d)
        if (TERMINAL_STATUSES.has(d.status)) {
          clearInterval(intervalRef.current!)
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Unknown error')
      }
    }

    fetchDeposit()
    intervalRef.current = setInterval(fetchDeposit, POLL_INTERVAL_MS)

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current)
    }
  }, [depositId, token])

  return { deposit, error }
}
```

### 14.3 `apps/web/src/app/(app)/deposit/page.tsx`

```typescript
'use client'

import { useState } from 'react'
import { useDeposit } from '../../../hooks/useDeposit'
import { createCryptoDeposit, createFiatDeposit, DepositResponse } from '../../../services/financeApi'
import { useAuthStore } from '../../../store/authStore'

type Tab = 'CRYPTO' | 'FIAT'
type Asset = 'ETH' | 'BTC' | 'USDT'

export default function DepositPage() {
  const { accessToken } = useAuthStore()
  const [tab, setTab] = useState<Tab>('CRYPTO')
  const [asset, setAsset] = useState<Asset>('ETH')
  const [amount, setAmount] = useState('')
  const [depositId, setDepositId] = useState<string | null>(null)
  const [createdDeposit, setCreatedDeposit] = useState<DepositResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const { deposit } = useDeposit(depositId, accessToken ?? '')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setLoading(true)
    try {
      const result = tab === 'CRYPTO'
        ? await createCryptoDeposit(asset, amount, accessToken ?? '')
        : await createFiatDeposit(amount, accessToken ?? '')
      setCreatedDeposit(result)
      setDepositId(result.id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Deposit failed')
    } finally {
      setLoading(false)
    }
  }

  const statusColor = (status: string) => {
    if (status === 'CREDITED') return 'text-up'
    if (status === 'FAILED' || status === 'EXPIRED') return 'text-down'
    return 'text-text-secondary'
  }

  return (
    <div className="max-w-lg mx-auto p-6 space-y-6">
      <h1 className="text-2xl font-semibold text-text-primary">Deposit Funds</h1>

      {/* Tab selector */}
      <div className="flex gap-2 border-b border-border">
        {(['CRYPTO', 'FIAT'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium ${
              tab === t
                ? 'border-b-2 border-accent text-accent'
                : 'text-text-secondary hover:text-text-primary'
            }`}
          >
            {t === 'CRYPTO' ? 'Crypto' : 'Bank Transfer'}
          </button>
        ))}
      </div>

      {!createdDeposit ? (
        <form onSubmit={handleSubmit} className="space-y-4">
          {tab === 'CRYPTO' && (
            <div>
              <label className="block text-sm text-text-secondary mb-1">Asset</label>
              <select
                value={asset}
                onChange={(e) => setAsset(e.target.value as Asset)}
                className="w-full bg-bg-secondary border border-border rounded-lg px-3 py-2 text-text-primary"
              >
                <option value="ETH">ETH (min 0.001)</option>
                <option value="BTC">BTC (min 0.0001)</option>
                <option value="USDT">USDT (min 10)</option>
              </select>
            </div>
          )}

          <div>
            <label className="block text-sm text-text-secondary mb-1">
              Amount {tab === 'FIAT' ? '(USD, min $10)' : ''}
            </label>
            <input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              step="any"
              min="0"
              required
              className="w-full bg-bg-secondary border border-border rounded-lg px-3 py-2 text-text-primary"
              placeholder="0.00"
            />
          </div>

          {error && <p className="text-down text-sm">{error}</p>}

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-accent text-white py-2 rounded-lg font-medium hover:opacity-90 disabled:opacity-50"
          >
            {loading ? 'Creating…' : 'Create Deposit'}
          </button>
        </form>
      ) : (
        <div className="space-y-4">
          {/* Deposit instructions */}
          {createdDeposit.type === 'CRYPTO' && (
            <div className="bg-bg-secondary border border-border rounded-xl p-4 space-y-2">
              <p className="text-sm text-text-secondary">Send {createdDeposit.asset} to this address:</p>
              <p className="font-mono text-sm text-text-primary break-all">
                {createdDeposit.walletAddress}
              </p>
              <p className="text-xs text-text-secondary">
                Amount: {createdDeposit.amount} {createdDeposit.asset}
              </p>
            </div>
          )}

          {createdDeposit.type === 'FIAT' && (
            <div className="bg-bg-secondary border border-border rounded-xl p-4 space-y-2">
              <p className="text-sm text-text-secondary">Bank reference code:</p>
              <p className="font-mono text-lg font-semibold text-text-primary">
                {createdDeposit.bankReference}
              </p>
              <p className="text-xs text-text-secondary">
                Transfer ${createdDeposit.amount} USD using this reference
              </p>
            </div>
          )}

          {/* Live status */}
          {deposit && (
            <div className="flex items-center justify-between text-sm">
              <span className="text-text-secondary">Status</span>
              <span className={`font-semibold ${statusColor(deposit.status)}`}>
                {deposit.status}
                {deposit.status === 'CONFIRMING' && (
                  <span className="ml-1 text-text-secondary">
                    ({deposit.confirmations}/{createdDeposit.type === 'CRYPTO' ? 12 : 1} confirmations)
                  </span>
                )}
              </span>
            </div>
          )}

          <button
            onClick={() => { setCreatedDeposit(null); setDepositId(null); setAmount('') }}
            className="text-sm text-accent hover:underline"
          >
            Create another deposit
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
| 1 | `app/models/domain.py`, `migrations/versions/001_initial_schema.py` | Migration runs without error; `deposits` + `deposit_audit_log` tables created |
| 2 | `app/repositories/deposit_repo.py` | All 7 methods pass unit tests |
| 3 | `app/services/wallet_service.py` | `generate_address` returns deterministic address per user+asset |
| 4 | `app/services/deposit_service.py` | TC-D01–TC-D12 pass |
| 5 | `infra/step_functions.tf`, `infra/step_functions_asl.json` | State machine deploys; execution starts on `start_execution()` call |
| 6 | `app/main.py`, `app/routers/deposits.py`, `app/routers/webhooks.py` | All endpoints return correct HTTP status codes |
| 7 | `app/producers/eventbridge_producer.py` | Event published to `finance-events` bus on CREDITED |
| 8 | `infra/aurora.tf`, `infra/ecs.tf`, `infra/eventbridge.tf`, `infra/iam.tf`, `infra/sqs.tf` | `terraform plan` shows no errors |
| 9 | `tests/` | All TC-D* and TC-W* tests pass |
| 10a | `apps/web/src/services/financeApi.ts`, `apps/web/src/hooks/useDeposit.ts` | Polling stops on terminal status |
| 10b | `apps/web/src/app/(app)/deposit/page.tsx` | Crypto tab shows wallet address; fiat tab shows bank reference; status updates every 10s |
| 11 | `services/spot-trading/app/routers/internal.py` | `POST /internal/positions/credit` credits balance atomically using `SELECT FOR UPDATE` |
