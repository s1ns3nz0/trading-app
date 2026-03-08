from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, field_validator


class SubmitOrderRequest(BaseModel):
    symbol: str
    side: str
    type: str
    price: Optional[str] = None          # required for LIMIT
    qty: str
    timeInForce: str = "GTC"

    @field_validator("side")
    @classmethod
    def validate_side(cls, v: str) -> str:
        if v not in ("BUY", "SELL"):
            raise ValueError("side must be BUY or SELL")
        return v

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("LIMIT", "MARKET"):
            raise ValueError("type must be LIMIT or MARKET")
        return v

    @field_validator("timeInForce")
    @classmethod
    def validate_tif(cls, v: str) -> str:
        if v not in ("GTC", "IOC", "FOK"):
            raise ValueError("timeInForce must be GTC, IOC, or FOK")
        return v


class OrderResponse(BaseModel):
    orderId: str
    userId: str
    symbol: str
    side: str
    type: str
    status: str
    price: Optional[str]
    origQty: str
    executedQty: str
    avgPrice: Optional[str]
    timeInForce: str
    createdAt: datetime
    updatedAt: datetime


class TradeResponse(BaseModel):
    tradeId: str
    symbol: str
    price: str
    qty: str
    buyerFee: str
    sellerFee: str
    executedAt: datetime


class PositionResponse(BaseModel):
    asset: str
    available: str
    locked: str
    total: str


class OrderBookResponse(BaseModel):
    symbol: str
    bids: List[List[str]]   # [[price, qty], ...]
    asks: List[List[str]]
