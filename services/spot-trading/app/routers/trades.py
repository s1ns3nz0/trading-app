from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request

from ..main import db_pool
from ..repositories.trade_repo import TradeRepository
from ..schemas import TradeResponse
from .orders import _get_user_id

router = APIRouter()


@router.get("/trades", response_model=list[TradeResponse])
async def list_trades(
    request: Request,
    symbol: Optional[str] = None,
    limit: int = 50,
):
    user_id = _get_user_id(request)
    async with db_pool.acquire() as conn:
        trade_list = await TradeRepository(conn).list_by_user(user_id, symbol, limit)
    return [
        TradeResponse(
            tradeId=t.id,
            symbol=t.symbol,
            price=str(t.price),
            qty=str(t.qty),
            buyerFee=str(t.buyer_fee),
            sellerFee=str(t.seller_fee),
            executedAt=t.executed_at,
        )
        for t in trade_list
    ]
