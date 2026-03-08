"""GET /market/orderbook/{symbol}?depth=20"""
import json

from fastapi import APIRouter, HTTPException, Query, Request

router = APIRouter()


@router.get("/orderbook/{symbol}")
async def get_orderbook(
    symbol: str,
    request: Request,
    depth: int = Query(default=20, ge=1, le=100),
):
    """Order book snapshot from Redis sorted sets."""
    redis = request.app.state.redis
    sym = symbol.upper()
    bids_key = f"orderbook:{sym}:bids"
    asks_key = f"orderbook:{sym}:asks"

    # ZREVRANGE for bids (highest price first), ZRANGE for asks (lowest first)
    raw_bids, raw_asks = await redis.zrevrange(bids_key, 0, depth - 1, withscores=True), \
                         await redis.zrange(asks_key, 0, depth - 1, withscores=True)

    if not raw_bids and not raw_asks:
        raise HTTPException(status_code=404, detail=f"No order book for {symbol}")

    bids = [{"price": str(score), "qty": json.loads(member)["qty"]} for member, score in raw_bids]
    asks = [{"price": str(score), "qty": json.loads(member)["qty"]} for member, score in raw_asks]

    return {"symbol": sym, "bids": bids, "asks": asks}
