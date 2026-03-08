"""GET /market/symbols"""
from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/symbols")
async def get_symbols(request: Request):
    """Available trading pairs with live status from Redis."""
    from ..config import settings
    redis = request.app.state.redis

    result = []
    for sym in settings.symbol_list:
        has_data = await redis.exists(f"ticker:{sym}")
        result.append({"symbol": sym, "active": bool(has_data)})

    return result
