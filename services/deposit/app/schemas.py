from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, field_validator


class CreateCryptoDepositRequest(BaseModel):
    asset: str
    amount: str

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
    id: str
    type: str
    asset: str
    amount: str
    status: str
    wallet_address: Optional[str] = None
    bank_reference: Optional[str] = None
    tx_hash: Optional[str] = None
    confirmations: int
    expires_at: datetime
    credited_at: Optional[datetime] = None
    created_at: datetime


class CryptoWebhookPayload(BaseModel):
    tx_hash: str
    address: str
    amount: str
    confirmations: int


class FiatWebhookPayload(BaseModel):
    bank_reference: str
    amount: str


class CreditRequest(BaseModel):
    """Internal: POST /internal/positions/credit payload from deposit service."""
    user_id: str
    asset: str
    amount: str
    deposit_id: str
