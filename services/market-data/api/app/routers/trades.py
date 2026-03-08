"""GET /market/trades/{symbol}?limit=50"""
import json

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter()


@router.get("/trades/{symbol}")
async def get_trades(
    symbol: str,
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
):
    """Recent trades from Redis list (LRANGE 0..limit-1)."""
    redis = request.app.state.redis
    sym = symbol.upper()
    key = f"trades:{sym}"

    raw = await redis.lrange(key, 0, limit - 1)
    if not raw:
        raise HTTPException(status_code=404, detail=f"No trades for {symbol}")

    trades = [json.loads(entry) for entry in raw]
    return {"symbol": sym, "trades": trades}
