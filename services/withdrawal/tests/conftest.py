import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from ..app.models.domain import WithdrawalRequest, WithdrawalType, WithdrawalStatus


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo._conn = AsyncMock()
    repo.create = AsyncMock()
    repo.get = AsyncMock()
    repo.update_status = AsyncMock()
    repo.list_by_user = AsyncMock(return_value=[])
    repo.get_daily_executed_sum = AsyncMock(return_value=Decimal("0"))
    repo.get_cancellable = AsyncMock(return_value=None)
    return repo


@pytest.fixture
def mock_aml(mock_repo):
    from ..app.services.aml_service import AMLService
    svc = AMLService(repo=mock_repo)
    return svc


@pytest.fixture
def mock_step_fn():
    svc = AsyncMock()
    svc.start_execution = AsyncMock(
        return_value="arn:aws:states:ap-northeast-2:123:execution:withdrawal-workflow:w-001"
    )
    return svc


@pytest.fixture
def pending_crypto_withdrawal():
    return WithdrawalRequest(
        id="w-uuid-001",
        user_id="user-001",
        type=WithdrawalType.CRYPTO,
        asset="ETH",
        amount=Decimal("0.5"),
        status=WithdrawalStatus.PENDING,
        to_address="0xabc123def456abc123def456abc123def456abc1",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def pending_fiat_withdrawal():
    return WithdrawalRequest(
        id="w-uuid-002",
        user_id="user-001",
        type=WithdrawalType.FIAT,
        asset="USD",
        amount=Decimal("500"),
        status=WithdrawalStatus.PENDING,
        bank_account_number="123456789",
        bank_routing_number="021000021",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
