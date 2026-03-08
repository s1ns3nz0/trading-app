from fastapi import APIRouter
from . import ticker, orderbook, trades, candles, symbols

router = APIRouter()
router.include_router(ticker.router,    prefix="/market", tags=["ticker"])
router.include_router(orderbook.router, prefix="/market", tags=["orderbook"])
router.include_router(trades.router,    prefix="/market", tags=["trades"])
router.include_router(candles.router,   prefix="/market", tags=["candles"])
router.include_router(symbols.router,   prefix="/market", tags=["symbols"])
