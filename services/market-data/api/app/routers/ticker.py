"""GET /market/ticker/{symbol} and GET /market/ticker"""
from fastapi import APIRouter, HTTPException, Request

from ..schemas import TickerResponse

router = APIRouter()


@router.get("/ticker/{symbol}", response_model=TickerResponse)
async def get_ticker(symbol: str, request: Request):
    """Current 24h ticker from Redis hash. O(1) read."""
    redis = request.app.state.redis
    key = f"ticker:{symbol.upper()}"
    data = await redis.hgetall(key)
    if not data:
        raise HTTPException(status_code=404, detail=f"No ticker data for {symbol}")
    return {"symbol": symbol.upper(), **data}


@router.get("/ticker")
async def get_all_tickers(request: Request):
    """All symbols ticker list."""
    from ..config import settings
    redis = request.app.state.redis

    result = []
    for sym in settings.symbol_list:
        data = await redis.hgetall(f"ticker:{sym}")
        if data:
            result.append({"symbol": sym, **data})
    return result
