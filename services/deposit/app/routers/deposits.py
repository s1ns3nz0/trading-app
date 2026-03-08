from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request

from ..middleware.auth import require_user_id
from ..models.domain import DepositRequest
from ..schemas import (
    CreateCryptoDepositRequest,
    CreateFiatDepositRequest,
    DepositResponse,
)

router = APIRouter(prefix="/deposits")


def _to_response(d: DepositRequest) -> DepositResponse:
    return DepositResponse(
        id=d.id,
        type=d.type.value,
        asset=d.asset,
        amount=str(d.amount),
        status=d.status.value,
        wallet_address=d.wallet_address,
        bank_reference=d.bank_reference,
        tx_hash=d.tx_hash,
        confirmations=d.confirmations,
        expires_at=d.expires_at,
        credited_at=d.credited_at,
        created_at=d.created_at,
    )


@router.post("/crypto", response_model=DepositResponse, status_code=201)
async def create_crypto_deposit(
    body: CreateCryptoDepositRequest,
    request: Request,
    user_id: str = Depends(require_user_id),
):
    from ..main import db_pool, deposit_svc
    from ..repositories.deposit_repo import PostgresDepositRepository

    try:
        async with db_pool.acquire() as conn:
            deposit_svc._repo = PostgresDepositRepository(conn)
            deposit = await deposit_svc.create_crypto_deposit(
                user_id, body.asset, Decimal(body.amount)
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _to_response(deposit)


@router.post("/fiat", response_model=DepositResponse, status_code=201)
async def create_fiat_deposit(
    body: CreateFiatDepositRequest,
    request: Request,
    user_id: str = Depends(require_user_id),
):
    from ..main import db_pool, deposit_svc
    from ..repositories.deposit_repo import PostgresDepositRepository

    try:
        async with db_pool.acquire() as conn:
            deposit_svc._repo = PostgresDepositRepository(conn)
            deposit = await deposit_svc.create_fiat_deposit(
                user_id, Decimal(body.amount)
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return _to_response(deposit)


@router.get("/{deposit_id}", response_model=DepositResponse)
async def get_deposit(
    deposit_id: str,
    user_id: str = Depends(require_user_id),
):
    from ..main import db_pool
    from ..repositories.deposit_repo import PostgresDepositRepository

    async with db_pool.acquire() as conn:
        deposit = await PostgresDepositRepository(conn).get(deposit_id)
    if not deposit or deposit.user_id != user_id:
        raise HTTPException(status_code=404, detail="Deposit not found")
    return _to_response(deposit)


@router.get("", response_model=list[DepositResponse])
async def list_deposits(user_id: str = Depends(require_user_id)):
    from ..main import db_pool
    from ..repositories.deposit_repo import PostgresDepositRepository

    async with db_pool.acquire() as conn:
        deposits = await PostgresDepositRepository(conn).list_by_user(user_id)
    return [_to_response(d) for d in deposits]
