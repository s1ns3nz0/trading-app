from fastapi import APIRouter, HTTPException

from ..main import engines
from ..schemas import OrderBookResponse

router = APIRouter()


@router.get("/orderbook/{symbol}", response_model=OrderBookResponse)
async def get_orderbook(symbol: str, levels: int = 20):
    if symbol not in engines:
        raise HTTPException(status_code=404, detail=f"No order book for symbol: {symbol}")
    snap = engines[symbol].depth_snapshot(levels=min(levels, 50))
    return OrderBookResponse(**snap)
