import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from ..app.models.domain import DepositRequest, DepositType, DepositStatus


@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo._conn = AsyncMock()
    repo.create = AsyncMock()
    repo.get = AsyncMock()
    repo.get_by_tx_hash = AsyncMock(return_value=None)
    repo.get_by_bank_reference = AsyncMock(return_value=None)
    repo.update_status = AsyncMock()
    repo.list_by_user = AsyncMock(return_value=[])
    repo.get_expired = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_wallet():
    wallet = MagicMock()
    wallet.generate_address = MagicMock(
        return_value="0xabc123def456abc123def456abc123def456abc1"
    )
    wallet.validate_address = MagicMock(return_value=True)
    return wallet


@pytest.fixture
def mock_step_fn():
    svc = AsyncMock()
    svc.start_execution = AsyncMock(
        return_value=(
            "arn:aws:states:ap-northeast-2:123456789:execution:"
            "deposit-workflow:dep-uuid-001"
        )
    )
    return svc


@pytest.fixture
def pending_crypto_deposit():
    return DepositRequest(
        id="dep-uuid-001",
        user_id="user-001",
        type=DepositType.CRYPTO,
        asset="ETH",
        amount=Decimal("0.5"),
        status=DepositStatus.PENDING,
        wallet_address="0xabc123def456abc123def456abc123def456abc1",
        required_confirmations=12,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def pending_fiat_deposit():
    return DepositRequest(
        id="dep-uuid-002",
        user_id="user-001",
        type=DepositType.FIAT,
        asset="USD",
        amount=Decimal("100"),
        status=DepositStatus.PENDING,
        bank_reference="DEP-ABCDEF12",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def app():
    """FastAPI test app with mocked dependencies."""
    from fastapi.testclient import TestClient
    from ..app.main import app as fastapi_app
    return fastapi_app
