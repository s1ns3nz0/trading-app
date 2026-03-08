from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import httpx

from ..config import settings
from ..models.domain import (
    MINIMUM_AMOUNTS,
    REQUIRED_CONFIRMATIONS,
    DepositRequest,
    DepositStatus,
    DepositType,
)
from ..repositories.deposit_repo import DepositRepository, _row_to_deposit
from .step_fn_service import StepFnService
from .wallet_service import WalletService


class DepositService:
    def __init__(
        self,
        repo: Optional[DepositRepository],
        wallet_svc: WalletService,
        step_fn_svc: StepFnService,
    ) -> None:
        self._repo = repo
        self._wallet = wallet_svc
        self._step_fn = step_fn_svc

    # ── Create ─────────────────────────────────────────────────────────────────

    async def create_crypto_deposit(
        self, user_id: str, asset: str, amount: Decimal
    ) -> DepositRequest:
        _validate_amount(asset, amount)
        address = self._wallet.generate_address(user_id, asset)
        deposit = DepositRequest(
            id=DepositRequest.new_id(),
            user_id=user_id,
            type=DepositType.CRYPTO,
            asset=asset,
            amount=amount,
            wallet_address=address,
            required_confirmations=REQUIRED_CONFIRMATIONS.get(asset, 12),
            expires_at=datetime.now(timezone.utc)
            + timedelta(hours=settings.deposit_expiry_hours),
        )
        return await self._repo.create(deposit)

    async def create_fiat_deposit(
        self, user_id: str, amount: Decimal
    ) -> DepositRequest:
        _validate_amount("USD", amount)
        bank_ref = _generate_bank_reference()
        deposit = DepositRequest(
            id=DepositRequest.new_id(),
            user_id=user_id,
            type=DepositType.FIAT,
            asset="USD",
            amount=amount,
            bank_reference=bank_ref,
            expires_at=datetime.now(timezone.utc)
            + timedelta(hours=settings.deposit_expiry_hours),
        )
        return await self._repo.create(deposit)

    # ── Webhook Processing ─────────────────────────────────────────────────────

    async def process_crypto_webhook(
        self,
        tx_hash: str,
        address: str,
        amount: Decimal,
        confirmations: int,
    ) -> Optional[DepositRequest]:
        """
        Idempotent: if tx_hash already exists in CONFIRMING+ state, return existing.
        """
        existing = await self._repo.get_by_tx_hash(tx_hash)
        if existing and existing.status not in (DepositStatus.PENDING,):
            return existing

        deposit = await _find_by_address(self._repo, address)
        if not deposit:
            raise ValueError(f"No PENDING deposit for address {address}")

        execution_arn = await self._step_fn.start_execution(deposit.id)

        await self._repo.update_status(
            deposit.id,
            DepositStatus.CONFIRMING,
            note=f"Webhook received tx_hash={tx_hash}",
            tx_hash=tx_hash,
            confirmations=confirmations,
            step_fn_execution_arn=execution_arn,
        )
        return await self._repo.get(deposit.id)

    async def process_fiat_webhook(
        self,
        bank_reference: str,
        amount: Decimal,
    ) -> Optional[DepositRequest]:
        """Idempotent: duplicate bank_reference webhook returns existing deposit."""
        deposit = await self._repo.get_by_bank_reference(bank_reference)
        if not deposit:
            raise ValueError(f"No deposit for bank_reference={bank_reference}")
        if deposit.status != DepositStatus.PENDING:
            return deposit

        execution_arn = await self._step_fn.start_execution(deposit.id)

        await self._repo.update_status(
            deposit.id,
            DepositStatus.CONFIRMING,
            note="Fiat bank webhook received",
            step_fn_execution_arn=execution_arn,
        )
        return await self._repo.get(deposit.id)

    # ── Credit Balance ─────────────────────────────────────────────────────────

    async def credit_balance(self, deposit_id: str) -> None:
        """
        Called by Step Functions after confirmation.
        Calls spot-trading internal API, then updates status to CREDITED.
        Idempotent: if already CREDITED, returns immediately.
        """
        deposit = await self._repo.get(deposit_id)
        if not deposit:
            raise ValueError(f"Deposit {deposit_id} not found")
        if deposit.status == DepositStatus.CREDITED:
            return
        if deposit.status != DepositStatus.CONFIRMED:
            raise ValueError(
                f"Cannot credit deposit in status {deposit.status}"
            )

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.spot_trading_internal_url}/internal/positions/credit",
                headers={"X-Internal-Token": settings.internal_token},
                json={
                    "user_id": deposit.user_id,
                    "asset": deposit.asset,
                    "amount": str(deposit.amount),
                    "deposit_id": deposit.id,
                },
            )
            resp.raise_for_status()

        now = datetime.now(timezone.utc)
        await self._repo.update_status(
            deposit.id,
            DepositStatus.CREDITED,
            note="Balance credited to spot-trading position",
            credited_at=now,
        )

    # ── Expiry ────────────────────────────────────────────────────────────────

    async def expire_pending_deposits(self) -> int:
        """Batch expire PENDING deposits past expires_at. Returns count expired."""
        expired = await self._repo.get_expired()
        for d in expired:
            await self._repo.update_status(
                d.id, DepositStatus.EXPIRED, note="Expired after 24h"
            )
        return len(expired)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _validate_amount(asset: str, amount: Decimal) -> None:
    minimum = MINIMUM_AMOUNTS.get(asset)
    if minimum and amount < minimum:
        raise ValueError(
            f"Amount {amount} below minimum {minimum} for {asset}"
        )


def _generate_bank_reference() -> str:
    return "DEP-" + secrets.token_hex(8).upper()


async def _find_by_address(
    repo: DepositRepository, address: str
) -> Optional[DepositRequest]:
    rows = await repo._conn.fetch(
        "SELECT * FROM finance.deposits "
        "WHERE wallet_address = $1 AND status = 'PENDING'",
        address,
    )
    if rows:
        return _row_to_deposit(rows[0])
    return None
