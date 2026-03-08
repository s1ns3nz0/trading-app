"""
Tests — DepositService core logic.

Coverage:
  TC-D01  create crypto deposit success
  TC-D02  create crypto deposit below minimum → ValueError
  TC-D03  create fiat deposit success
  TC-D04  create fiat deposit below minimum → ValueError
  TC-D05  process_crypto_webhook — success → CONFIRMING
  TC-D06  process_crypto_webhook — duplicate tx_hash → idempotent return
  TC-D07  process_fiat_webhook — success → CONFIRMING
  TC-D08  process_fiat_webhook — duplicate → idempotent return
  TC-D09  credit_balance — success → CREDITED
  TC-D10  credit_balance — already CREDITED → idempotent no-op
  TC-D11  credit_balance — deposit not found → ValueError
  TC-D12  expire_pending_deposits — expires 2 deposits
"""
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from ..app.services.deposit_service import DepositService, _find_by_address
from ..app.models.domain import DepositStatus, DepositType


@pytest.fixture
def svc(mock_repo, mock_wallet, mock_step_fn):
    return DepositService(mock_repo, mock_wallet, mock_step_fn)


# TC-D01
@pytest.mark.asyncio
async def test_create_crypto_deposit_success(svc, mock_repo, pending_crypto_deposit):
    mock_repo.create.return_value = pending_crypto_deposit
    result = await svc.create_crypto_deposit("user-001", "ETH", Decimal("0.5"))
    assert result.asset == "ETH"
    assert result.wallet_address is not None
    mock_repo.create.assert_called_once()
    call_arg = mock_repo.create.call_args[0][0]
    assert call_arg.type == DepositType.CRYPTO
    assert call_arg.required_confirmations == 12


# TC-D02
@pytest.mark.asyncio
async def test_create_crypto_deposit_below_minimum(svc):
    with pytest.raises(ValueError, match="below minimum"):
        await svc.create_crypto_deposit("user-001", "ETH", Decimal("0.0001"))


# TC-D03
@pytest.mark.asyncio
async def test_create_fiat_deposit_success(svc, mock_repo, pending_fiat_deposit):
    mock_repo.create.return_value = pending_fiat_deposit
    result = await svc.create_fiat_deposit("user-001", Decimal("100"))
    assert result.bank_reference.startswith("DEP-")
    mock_repo.create.assert_called_once()
    call_arg = mock_repo.create.call_args[0][0]
    assert call_arg.type == DepositType.FIAT
    assert call_arg.asset == "USD"


# TC-D04
@pytest.mark.asyncio
async def test_create_fiat_deposit_below_minimum(svc):
    with pytest.raises(ValueError, match="below minimum"):
        await svc.create_fiat_deposit("user-001", Decimal("5"))


# TC-D05
@pytest.mark.asyncio
async def test_process_crypto_webhook_success(
    svc, mock_repo, mock_step_fn, pending_crypto_deposit
):
    mock_repo.get_by_tx_hash.return_value = None
    mock_repo.get.return_value = pending_crypto_deposit

    with patch(
        "services.deposit.app.services.deposit_service._find_by_address",
        new_callable=AsyncMock,
        return_value=pending_crypto_deposit,
    ):
        result = await svc.process_crypto_webhook(
            tx_hash="0xdeadbeef",
            address=pending_crypto_deposit.wallet_address,
            amount=Decimal("0.5"),
            confirmations=1,
        )

    mock_step_fn.start_execution.assert_called_once_with(pending_crypto_deposit.id)
    mock_repo.update_status.assert_called_once()
    update_args = mock_repo.update_status.call_args
    assert update_args.args[1] == DepositStatus.CONFIRMING
    assert update_args.kwargs.get("tx_hash") == "0xdeadbeef"


# TC-D06
@pytest.mark.asyncio
async def test_process_crypto_webhook_idempotent(svc, mock_repo, pending_crypto_deposit):
    confirming = pending_crypto_deposit
    confirming.status = DepositStatus.CONFIRMING
    mock_repo.get_by_tx_hash.return_value = confirming

    result = await svc.process_crypto_webhook(
        tx_hash="0xdeadbeef", address="any", amount=Decimal("0.5"), confirmations=2
    )
    assert result.status == DepositStatus.CONFIRMING
    mock_repo.update_status.assert_not_called()
    mock_repo.get_by_tx_hash.assert_called_once_with("0xdeadbeef")


# TC-D07
@pytest.mark.asyncio
async def test_process_fiat_webhook_success(
    svc, mock_repo, mock_step_fn, pending_fiat_deposit
):
    mock_repo.get_by_bank_reference.return_value = pending_fiat_deposit
    pending_fiat_deposit.status = DepositStatus.PENDING

    updated = pending_fiat_deposit
    updated.status = DepositStatus.CONFIRMING
    mock_repo.get.return_value = updated

    result = await svc.process_fiat_webhook(
        bank_reference="DEP-ABCDEF12", amount=Decimal("100")
    )

    mock_step_fn.start_execution.assert_called_once_with(pending_fiat_deposit.id)
    mock_repo.update_status.assert_called_once()


# TC-D08
@pytest.mark.asyncio
async def test_process_fiat_webhook_idempotent(svc, mock_repo, pending_fiat_deposit):
    pending_fiat_deposit.status = DepositStatus.CONFIRMING
    mock_repo.get_by_bank_reference.return_value = pending_fiat_deposit

    result = await svc.process_fiat_webhook(
        bank_reference="DEP-ABCDEF12", amount=Decimal("100")
    )
    assert result.status == DepositStatus.CONFIRMING
    mock_repo.update_status.assert_not_called()


# TC-D09
@pytest.mark.asyncio
async def test_credit_balance_success(svc, mock_repo, pending_crypto_deposit):
    confirmed = pending_crypto_deposit
    confirmed.status = DepositStatus.CONFIRMED
    mock_repo.get.return_value = confirmed

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient") as mock_client:
        mock_client.return_value.__aenter__.return_value.post = AsyncMock(
            return_value=mock_resp
        )
        await svc.credit_balance(confirmed.id)

    mock_resp.raise_for_status.assert_called_once()
    mock_repo.update_status.assert_called_once()
    call_args = mock_repo.update_status.call_args
    assert call_args.args[1] == DepositStatus.CREDITED
    assert call_args.kwargs.get("credited_at") is not None


# TC-D10
@pytest.mark.asyncio
async def test_credit_balance_idempotent(svc, mock_repo, pending_crypto_deposit):
    credited = pending_crypto_deposit
    credited.status = DepositStatus.CREDITED
    mock_repo.get.return_value = credited

    await svc.credit_balance(credited.id)
    mock_repo.update_status.assert_not_called()


# TC-D11
@pytest.mark.asyncio
async def test_credit_balance_not_found(svc, mock_repo):
    mock_repo.get.return_value = None
    with pytest.raises(ValueError, match="not found"):
        await svc.credit_balance("nonexistent-id")


# TC-D12
@pytest.mark.asyncio
async def test_expire_pending_deposits(
    svc, mock_repo, pending_crypto_deposit, pending_fiat_deposit
):
    mock_repo.get_expired.return_value = [pending_crypto_deposit, pending_fiat_deposit]
    count = await svc.expire_pending_deposits()
    assert count == 2
    assert mock_repo.update_status.call_count == 2
    for call in mock_repo.update_status.call_args_list:
        assert call.args[1] == DepositStatus.EXPIRED
        assert "Expired" in call.kwargs.get("note", "")
