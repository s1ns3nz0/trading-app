from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

import httpx

from ..config import settings
from ..models.domain import (
    MAXIMUM_AMOUNTS, MINIMUM_AMOUNTS,
    WithdrawalRequest, WithdrawalStatus, WithdrawalType,
)
from ..repositories.withdrawal_repo import WithdrawalRepository
from ..services.aml_service import AMLService
from ..services.step_fn_service import StepFnService


class WithdrawalService:
    def __init__(
        self,
        repo: Optional[WithdrawalRepository],
        aml_svc: AMLService,
        step_fn_svc: StepFnService,
    ) -> None:
        self._repo    = repo
        self._aml     = aml_svc
        self._step_fn = step_fn_svc

    # ── Create ─────────────────────────────────────────────────────────────────

    async def create_crypto_withdrawal(
        self,
        user_id: str,
        asset: str,
        amount: Decimal,
        to_address: str,
    ) -> WithdrawalRequest:
        _validate_amount(asset, amount)
        _validate_crypto_address(to_address, asset)
        if not await self._aml.check_daily_limit(user_id, asset, amount):
            raise ValueError("Daily withdrawal limit exceeded")

        w = WithdrawalRequest(
            id=WithdrawalRequest.new_id(),
            user_id=user_id,
            type=WithdrawalType.CRYPTO,
            asset=asset,
            amount=amount,
            to_address=to_address,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        return await self._repo.create(w)

    async def create_fiat_withdrawal(
        self,
        user_id: str,
        amount: Decimal,
        bank_account_number: str,
        bank_routing_number: str,
    ) -> WithdrawalRequest:
        _validate_amount("USD", amount)
        if not await self._aml.check_daily_limit(user_id, "USD", amount):
            raise ValueError("Daily withdrawal limit exceeded")

        w = WithdrawalRequest(
            id=WithdrawalRequest.new_id(),
            user_id=user_id,
            type=WithdrawalType.FIAT,
            asset="USD",
            amount=amount,
            bank_account_number=bank_account_number,
            bank_routing_number=bank_routing_number,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        return await self._repo.create(w)

    # ── Reserve (called by Step Functions) ─────────────────────────────────────

    async def reserve_balance(self, withdrawal_id: str) -> None:
        """
        Deduct balance from spot-trading available balance.
        Updates status PENDING → PROCESSING on success.
        Raises ValueError if deduct fails (insufficient funds).
        """
        w = await self._repo.get(withdrawal_id)
        if not w:
            raise ValueError(f"Withdrawal {withdrawal_id} not found")
        if w.status != WithdrawalStatus.PENDING:
            return   # idempotent

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.spot_trading_internal_url}/internal/positions/deduct",
                headers={"X-Internal-Token": settings.internal_token},
                json={
                    "user_id":       w.user_id,
                    "asset":         w.asset,
                    "amount":        str(w.amount),
                    "withdrawal_id": w.id,
                },
            )
            if resp.status_code == 422:
                raise ValueError("Insufficient balance")
            resp.raise_for_status()

        now = datetime.now(timezone.utc)
        await self._repo.update_status(
            w.id,
            WithdrawalStatus.PROCESSING,
            note="Balance reserved — deducted from spot-trading",
            reserved_at=now,
        )

    # ── Execute ────────────────────────────────────────────────────────────────

    async def execute_crypto(self, withdrawal_id: str) -> None:
        """Mock on-chain send. Generates deterministic tx_hash."""
        w = await self._repo.get(withdrawal_id)
        if not w:
            raise ValueError(f"Withdrawal {withdrawal_id} not found")
        if w.status == WithdrawalStatus.EXECUTED:
            return   # idempotent
        if w.status != WithdrawalStatus.PROCESSING:
            raise ValueError(f"Cannot execute in status {w.status}")

        # Mock: generate tx_hash (real: call hot wallet signing service)
        tx_hash = "0x" + secrets.token_hex(32)
        now = datetime.now(timezone.utc)

        await self._repo.update_status(
            w.id,
            WithdrawalStatus.EXECUTED,
            note=f"On-chain tx sent: {tx_hash}",
            tx_hash=tx_hash,
            executed_at=now,
        )

    async def execute_fiat(self, withdrawal_id: str) -> None:
        """Mock bank transfer initiation."""
        w = await self._repo.get(withdrawal_id)
        if not w:
            raise ValueError(f"Withdrawal {withdrawal_id} not found")
        if w.status == WithdrawalStatus.EXECUTED:
            return   # idempotent
        if w.status != WithdrawalStatus.PROCESSING:
            raise ValueError(f"Cannot execute in status {w.status}")

        now = datetime.now(timezone.utc)
        await self._repo.update_status(
            w.id,
            WithdrawalStatus.EXECUTED,
            note="Bank transfer initiated (mock)",
            executed_at=now,
        )

    # ── Reject / Fail / Cancel ─────────────────────────────────────────────────

    async def reject_withdrawal(
        self, withdrawal_id: str, reason: str
    ) -> None:
        """Reject (e.g., AML fail). Releases reserved balance if PROCESSING."""
        w = await self._repo.get(withdrawal_id)
        if not w:
            raise ValueError(f"Withdrawal {withdrawal_id} not found")

        await self._repo.update_status(
            w.id,
            WithdrawalStatus.REJECTED,
            note=f"Rejected: {reason}",
            rejection_reason=reason,
        )
        if w.status == WithdrawalStatus.PROCESSING:
            await self._release_balance(w)

    async def fail_withdrawal(
        self, withdrawal_id: str, reason: str
    ) -> None:
        """Mark as FAILED (execution error). Releases reserved balance."""
        w = await self._repo.get(withdrawal_id)
        if not w:
            raise ValueError(f"Withdrawal {withdrawal_id} not found")

        await self._repo.update_status(
            w.id,
            WithdrawalStatus.FAILED,
            note=f"Failed: {reason}",
        )
        if w.status == WithdrawalStatus.PROCESSING:
            await self._release_balance(w)

    async def cancel_withdrawal(
        self, withdrawal_id: str, user_id: str
    ) -> None:
        """User-initiated cancel. Only allowed in PENDING state."""
        w = await self._repo.get_cancellable(withdrawal_id, user_id)
        if not w:
            raise ValueError("Withdrawal not found or cannot be cancelled")

        await self._repo.update_status(
            w.id,
            WithdrawalStatus.CANCELLED,
            note="Cancelled by user",
        )

    # ── Internal ───────────────────────────────────────────────────────────────

    async def _release_balance(self, w: WithdrawalRequest) -> None:
        """Credit balance back to spot-trading (reversal)."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{settings.spot_trading_internal_url}/internal/positions/credit",
                headers={"X-Internal-Token": settings.internal_token},
                json={
                    "user_id":    w.user_id,
                    "asset":      w.asset,
                    "amount":     str(w.amount),
                    "deposit_id": w.id,   # reuse credit API (deposit_id field)
                },
            )
            resp.raise_for_status()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _validate_amount(asset: str, amount: Decimal) -> None:
    minimum = MINIMUM_AMOUNTS.get(asset)
    maximum = MAXIMUM_AMOUNTS.get(asset)
    if minimum and amount < minimum:
        raise ValueError(f"Amount below minimum {minimum} for {asset}")
    if maximum and amount > maximum:
        raise ValueError(f"Amount exceeds maximum {maximum} for {asset}")


def _validate_crypto_address(address: str, asset: str) -> None:
    if asset in ("ETH", "USDT"):
        if not (address.startswith("0x") and len(address) == 42):
            raise ValueError(f"Invalid {asset} address format")
    elif asset == "BTC":
        if not (address.startswith("bc1q") and len(address) == 42):
            raise ValueError("Invalid BTC address format")
    else:
        raise ValueError(f"Unknown asset {asset}")
