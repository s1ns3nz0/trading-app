"""
Internal API endpoints — not exposed through the public API Gateway.
Called service-to-service using X-Internal-Token authentication.
"""
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request

from ..config import settings
from ..main import db_pool
from ..repositories.position_repo import PositionRepository

router = APIRouter(prefix="/internal")


@router.post("/positions/credit", status_code=204)
async def credit_position(request: Request):
    """
    Credit a user's position balance after a confirmed deposit.
    Called by the deposit service after Step Functions confirmation.

    Body: { user_id, asset, amount, deposit_id }
    """
    token = request.headers.get("X-Internal-Token", "")
    if token != settings.internal_token:
        raise HTTPException(status_code=401, detail="Invalid internal token")

    body = await request.json()
    user_id = body["user_id"]
    asset = body["asset"]
    amount = Decimal(str(body["amount"]))

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            repo = PositionRepository(conn)
            await repo._settle_credit(user_id, asset, amount)


@router.post("/positions/deduct", status_code=204)
async def deduct_position(request: Request):
    """
    Deduct from a user's available balance (withdrawal reservation).
    Returns 422 if insufficient balance.
    Called by the withdrawal service before Step Functions execution.

    Body: { user_id, asset, amount, withdrawal_id }
    """
    token = request.headers.get("X-Internal-Token", "")
    if token != settings.internal_token:
        raise HTTPException(status_code=401, detail="Invalid internal token")

    body = await request.json()
    user_id = body["user_id"]
    asset = body["asset"]
    amount = Decimal(str(body["amount"]))

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            repo = PositionRepository(conn)
            success = await repo.lock_for_order(user_id, asset, amount)
            if not success:
                raise HTTPException(
                    status_code=422, detail="Insufficient balance"
                )
