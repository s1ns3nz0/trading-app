from decimal import Decimal
from fastapi import APIRouter, Depends, HTTPException, Request

from ..middleware.auth import require_user_id
from ..models.domain import WithdrawalRequest
from ..schemas import (
    CreateCryptoWithdrawalRequest,
    CreateFiatWithdrawalRequest,
    WithdrawalResponse,
)

router = APIRouter(prefix="/withdrawals")


def _to_response(w: WithdrawalRequest) -> WithdrawalResponse:
    return WithdrawalResponse(
        id=w.id,
        type=w.type.value,
        asset=w.asset,
        amount=str(w.amount),
        status=w.status.value,
        to_address=w.to_address,
        tx_hash=w.tx_hash,
        bank_account_number=w.bank_account_number,
        rejection_reason=w.rejection_reason,
        reserved_at=w.reserved_at,
        executed_at=w.executed_at,
        expires_at=w.expires_at,
        created_at=w.created_at,
    )


@router.post("/crypto", response_model=WithdrawalResponse, status_code=201)
async def create_crypto_withdrawal(
    body: CreateCryptoWithdrawalRequest,
    user_id: str = Depends(require_user_id),
):
    from ..main import db_pool, withdrawal_svc
    from ..repositories.withdrawal_repo import PostgresWithdrawalRepository

    try:
        async with db_pool.acquire() as conn:
            withdrawal_svc._repo = PostgresWithdrawalRepository(conn)
            withdrawal_svc._aml._repo = PostgresWithdrawalRepository(conn)
            w = await withdrawal_svc.create_crypto_withdrawal(
                user_id, body.asset, Decimal(body.amount), body.to_address
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _to_response(w)


@router.post("/fiat", response_model=WithdrawalResponse, status_code=201)
async def create_fiat_withdrawal(
    body: CreateFiatWithdrawalRequest,
    user_id: str = Depends(require_user_id),
):
    from ..main import db_pool, withdrawal_svc
    from ..repositories.withdrawal_repo import PostgresWithdrawalRepository

    try:
        async with db_pool.acquire() as conn:
            withdrawal_svc._repo = PostgresWithdrawalRepository(conn)
            withdrawal_svc._aml._repo = PostgresWithdrawalRepository(conn)
            w = await withdrawal_svc.create_fiat_withdrawal(
                user_id, Decimal(body.amount),
                body.bank_account_number, body.bank_routing_number,
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _to_response(w)


@router.get("/{withdrawal_id}", response_model=WithdrawalResponse)
async def get_withdrawal(
    withdrawal_id: str,
    user_id: str = Depends(require_user_id),
):
    from ..main import db_pool
    from ..repositories.withdrawal_repo import PostgresWithdrawalRepository

    async with db_pool.acquire() as conn:
        w = await PostgresWithdrawalRepository(conn).get(withdrawal_id)
    if not w or w.user_id != user_id:
        raise HTTPException(status_code=404, detail="Withdrawal not found")
    return _to_response(w)


@router.get("", response_model=list[WithdrawalResponse])
async def list_withdrawals(user_id: str = Depends(require_user_id)):
    from ..main import db_pool
    from ..repositories.withdrawal_repo import PostgresWithdrawalRepository

    async with db_pool.acquire() as conn:
        withdrawals = await PostgresWithdrawalRepository(conn).list_by_user(user_id)
    return [_to_response(w) for w in withdrawals]


@router.delete("/{withdrawal_id}", status_code=204)
async def cancel_withdrawal(
    withdrawal_id: str,
    user_id: str = Depends(require_user_id),
):
    from ..main import db_pool, withdrawal_svc
    from ..repositories.withdrawal_repo import PostgresWithdrawalRepository

    try:
        async with db_pool.acquire() as conn:
            withdrawal_svc._repo = PostgresWithdrawalRepository(conn)
            await withdrawal_svc.cancel_withdrawal(withdrawal_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
