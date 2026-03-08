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
    amount:              str
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
