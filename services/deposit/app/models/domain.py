from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional


class DepositType(str, Enum):
    CRYPTO = "CRYPTO"
    FIAT = "FIAT"


class DepositStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMING = "CONFIRMING"
    CONFIRMED = "CONFIRMED"
    CREDITED = "CREDITED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


MINIMUM_AMOUNTS: dict[str, Decimal] = {
    "ETH": Decimal("0.001"),
    "BTC": Decimal("0.0001"),
    "USDT": Decimal("10"),
    "USD": Decimal("10"),
}

REQUIRED_CONFIRMATIONS: dict[str, int] = {
    "ETH": 12,
    "BTC": 6,
    "USDT": 12,
}


@dataclass
class DepositRequest:
    id: str
    user_id: str
    type: DepositType
    asset: str
    amount: Decimal
    status: DepositStatus = DepositStatus.PENDING
    wallet_address: Optional[str] = None
    tx_hash: Optional[str] = None
    bank_reference: Optional[str] = None
    confirmations: int = 0
    required_confirmations: int = 0
    step_fn_execution_arn: Optional[str] = None
    credited_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @staticmethod
    def new_id() -> str:
        return str(uuid.uuid4())
