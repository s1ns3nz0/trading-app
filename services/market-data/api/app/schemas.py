"""
Pydantic response models for the Market Data REST API.
All price/quantity fields are strings to preserve decimal precision.
"""
from pydantic import BaseModel


class TickerResponse(BaseModel):
    symbol: str
    lastPrice: str
    priceChange: str
    priceChangePct: str
    volume: str
    quoteVolume: str
    high: str
    low: str
    openPrice: str


class CandleResponse(BaseModel):
    openTime: int
    open: str
    high: str
    low: str
    close: str
    volume: str
    closeTime: int
