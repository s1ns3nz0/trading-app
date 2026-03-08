"""
Tests — WithdrawalService core logic.

Coverage:
  TC-W01  create crypto withdrawal success
  TC-W02  create crypto below minimum → ValueError
  TC-W03  create crypto above maximum → ValueError
  TC-W04  create crypto invalid address → ValueError
  TC-W05  create crypto AML limit exceeded → ValueError
  TC-W06  create fiat withdrawal success
  TC-W07  reserve_balance success → PROCESSING
  TC-W08  reserve_balance insufficient funds → ValueError
  TC-W09  reserve_balance idempotent (already PROCESSING)
  TC-W10  execute_crypto success → EXECUTED with tx_hash
  TC-W11  execute_crypto idempotent (already EXECUTED)
  TC-W12  execute_fiat success → EXECUTED
  TC-W13  reject_withdrawal releases balance (PROCESSING → REJECTED)
  TC-W14  fail_withdrawal releases balance (PROCESSING → FAILED)
  TC-W15  cancel_withdrawal PENDING → CANCELLED
  TC-W16  cancel_withdrawal PROCESSING → ValueError (409)
"""
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from ..app.services.withdrawal_service import WithdrawalService
from ..app.models.domain import WithdrawalStatus, WithdrawalType


@pytest.fixture
def svc(mock_repo, mock_aml, mock_step_fn):
    return WithdrawalService(mock_repo, mock_aml, mock_step_fn)


# TC-W01
@pytest.mark.asyncio
async def test_create_crypto_withdrawal_success(svc, mock_repo, pending_crypto_withdrawal):
    mock_repo.create.return_value = pending_crypto_withdrawal
    result = await svc.create_crypto_withdrawal(
        "user-001", "ETH", Decimal("0.5"),
        "0xabc123def456abc123def456abc123def456abc1"
    )
    assert result.asset == "ETH"
    assert result.to_address is not None
    mock_repo.create.assert_called_once()


# TC-W02
@pytest.mark.asyncio
async def test_create_crypto_below_minimum(svc):
    with pytest.raises(ValueError, match="below minimum"):
        await svc.create_crypto_withdrawal(
            "user-001", "ETH", Decimal("0.0001"),
            "0xabc123def456abc123def456abc123def456abc1"
        )


# TC-W03
@pytest.mark.asyncio
async def test_create_crypto_above_maximum(svc):
    with pytest.raises(ValueError, match="exceeds maximum"):
        await svc.create_crypto_withdrawal(
            "user-001", "ETH", Decimal("100"),
            "0xabc123def456abc123def456abc123def456abc1"
        )


# TC-W04
@pytest.mark.asyncio
async def test_create_crypto_invalid_address(svc):
    with pytest.raises(ValueError, match="Invalid ETH address"):
        await svc.create_crypto_withdrawal(
            "user-001", "ETH", Decimal("0.5"), "not-an-address"
        )


# TC-W05
@pytest.mark.asyncio
async def test_create_crypto_aml_exceeded(svc, mock_repo):
    mock_repo.get_daily_executed_sum.return_value = Decimal("20")  # 20 ETH = $60k
    with pytest.raises(ValueError, match="Daily withdrawal limit"):
        await svc.create_crypto_withdrawal(
            "user-001", "ETH", Decimal("0.5"),
            "0xabc123def456abc123def456abc123def456abc1"
        )


# TC-W06
@pytest.mark.asyncio
async def test_create_fiat_withdrawal_success(svc, mock_repo, pending_fiat_withdrawal):
    mock_repo.create.return_value = pending_fiat_withdrawal
    result = await svc.create_fiat_withdrawal(
        "user-001", Decimal("500"), "123456789", "021000021"
    )
    assert result.asset == "USD"
    assert result.bank_account_number == "123456789"


# TC-W07
@pytest.mark.asyncio
async def test_reserve_balance_success(svc, mock_repo, pending_crypto_withdrawal):
    mock_repo.get.return_value = pending_crypto_withdrawal

    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.raise_for_status = MagicMock()
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_resp
        )
        await svc.reserve_balance(pending_crypto_withdrawal.id)

    mock_repo.update_status.assert_called_once()
    assert mock_repo.update_status.call_args.args[1] == WithdrawalStatus.PROCESSING


# TC-W08
@pytest.mark.asyncio
async def test_reserve_balance_insufficient_funds(svc, mock_repo, pending_crypto_withdrawal):
    mock_repo.get.return_value = pending_crypto_withdrawal

    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.status_code = 422
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_resp
        )
        with pytest.raises(ValueError, match="Insufficient balance"):
            await svc.reserve_balance(pending_crypto_withdrawal.id)


# TC-W09
@pytest.mark.asyncio
async def test_reserve_balance_idempotent(svc, mock_repo, pending_crypto_withdrawal):
    pending_crypto_withdrawal.status = WithdrawalStatus.PROCESSING
    mock_repo.get.return_value = pending_crypto_withdrawal
    await svc.reserve_balance(pending_crypto_withdrawal.id)
    mock_repo.update_status.assert_not_called()


# TC-W10
@pytest.mark.asyncio
async def test_execute_crypto_success(svc, mock_repo, pending_crypto_withdrawal):
    pending_crypto_withdrawal.status = WithdrawalStatus.PROCESSING
    mock_repo.get.return_value = pending_crypto_withdrawal
    await svc.execute_crypto(pending_crypto_withdrawal.id)
    mock_repo.update_status.assert_called_once()
    call = mock_repo.update_status.call_args
    assert call.args[1] == WithdrawalStatus.EXECUTED
    assert call.kwargs.get("tx_hash", "").startswith("0x")


# TC-W11
@pytest.mark.asyncio
async def test_execute_crypto_idempotent(svc, mock_repo, pending_crypto_withdrawal):
    pending_crypto_withdrawal.status = WithdrawalStatus.EXECUTED
    mock_repo.get.return_value = pending_crypto_withdrawal
    await svc.execute_crypto(pending_crypto_withdrawal.id)
    mock_repo.update_status.assert_not_called()


# TC-W12
@pytest.mark.asyncio
async def test_execute_fiat_success(svc, mock_repo, pending_fiat_withdrawal):
    pending_fiat_withdrawal.status = WithdrawalStatus.PROCESSING
    mock_repo.get.return_value = pending_fiat_withdrawal
    await svc.execute_fiat(pending_fiat_withdrawal.id)
    mock_repo.update_status.assert_called_once()
    assert mock_repo.update_status.call_args.args[1] == WithdrawalStatus.EXECUTED


# TC-W13
@pytest.mark.asyncio
async def test_reject_releases_balance(svc, mock_repo, pending_crypto_withdrawal):
    pending_crypto_withdrawal.status = WithdrawalStatus.PROCESSING
    mock_repo.get.return_value = pending_crypto_withdrawal

    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_resp
        )
        await svc.reject_withdrawal(pending_crypto_withdrawal.id, "AML limit exceeded")

    assert mock_repo.update_status.call_args.args[1] == WithdrawalStatus.REJECTED
    mock_resp.raise_for_status.assert_called_once()   # credit called


# TC-W14
@pytest.mark.asyncio
async def test_fail_releases_balance(svc, mock_repo, pending_crypto_withdrawal):
    pending_crypto_withdrawal.status = WithdrawalStatus.PROCESSING
    mock_repo.get.return_value = pending_crypto_withdrawal

    with patch("httpx.AsyncClient") as mock_client:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_resp
        )
        await svc.fail_withdrawal(pending_crypto_withdrawal.id, "Execution error")

    assert mock_repo.update_status.call_args.args[1] == WithdrawalStatus.FAILED


# TC-W15
@pytest.mark.asyncio
async def test_cancel_pending(svc, mock_repo, pending_crypto_withdrawal):
    mock_repo.get_cancellable.return_value = pending_crypto_withdrawal
    await svc.cancel_withdrawal(pending_crypto_withdrawal.id, "user-001")
    assert mock_repo.update_status.call_args.args[1] == WithdrawalStatus.CANCELLED


# TC-W16
@pytest.mark.asyncio
async def test_cancel_processing_raises(svc, mock_repo):
    mock_repo.get_cancellable.return_value = None
    with pytest.raises(ValueError, match="cannot be cancelled"):
        await svc.cancel_withdrawal("w-uuid-001", "user-001")
