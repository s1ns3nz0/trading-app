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
