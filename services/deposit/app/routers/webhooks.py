import hashlib
import hmac
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request

from ..config import settings
from ..schemas import CryptoWebhookPayload, FiatWebhookPayload

router = APIRouter(prefix="/internal/webhooks")


async def _validate_hmac(request: Request) -> bytes:
    """Validates X-Webhook-Signature header (format: sha256=<hex>) against body."""
    signature = request.headers.get("X-Webhook-Signature", "")
    body = await request.body()
    expected = (
        "sha256="
        + hmac.new(
            settings.webhook_hmac_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
    )
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    return body


@router.post("/crypto")
async def crypto_webhook(request: Request):
    body_bytes = await _validate_hmac(request)
    payload = CryptoWebhookPayload.model_validate_json(body_bytes)

    from ..main import db_pool, deposit_svc
    from ..repositories.deposit_repo import PostgresDepositRepository

    try:
        async with db_pool.acquire() as conn:
            deposit_svc._repo = PostgresDepositRepository(conn)
            deposit = await deposit_svc.process_crypto_webhook(
                tx_hash=payload.tx_hash,
                address=payload.address,
                amount=Decimal(payload.amount),
                confirmations=payload.confirmations,
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"deposit_id": deposit.id, "status": deposit.status.value}


@router.post("/fiat")
async def fiat_webhook(request: Request):
    body_bytes = await _validate_hmac(request)
    payload = FiatWebhookPayload.model_validate_json(body_bytes)

    from ..main import db_pool, deposit_svc
    from ..repositories.deposit_repo import PostgresDepositRepository

    try:
        async with db_pool.acquire() as conn:
            deposit_svc._repo = PostgresDepositRepository(conn)
            deposit = await deposit_svc.process_fiat_webhook(
                bank_reference=payload.bank_reference,
                amount=Decimal(payload.amount),
            )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return {"deposit_id": deposit.id, "status": deposit.status.value}
