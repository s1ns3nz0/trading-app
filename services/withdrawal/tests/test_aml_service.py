"""
Tests — AMLService daily limit logic.

  TC-A01  under limit → True
  TC-A02  exactly at limit → True
  TC-A03  one cent over limit → False
  TC-A04  multi-asset aggregation
"""
import pytest
from decimal import Decimal
from ..app.services.aml_service import AMLService


@pytest.fixture
def aml(mock_repo):
    return AMLService(repo=mock_repo)


# TC-A01
@pytest.mark.asyncio
async def test_under_limit(aml, mock_repo):
    mock_repo.get_daily_executed_sum.return_value = Decimal("0")
    result = await aml.check_daily_limit("user-001", "USD", Decimal("1000"))
    assert result is True


# TC-A02
@pytest.mark.asyncio
async def test_exactly_at_limit(aml, mock_repo):
    mock_repo.get_daily_executed_sum.return_value = Decimal("0")
    result = await aml.check_daily_limit("user-001", "USD", Decimal("50000"))
    assert result is True


# TC-A03
@pytest.mark.asyncio
async def test_over_limit(aml, mock_repo):
    mock_repo.get_daily_executed_sum.return_value = Decimal("0")
    result = await aml.check_daily_limit("user-001", "USD", Decimal("50000.01"))
    assert result is False


# TC-A04
@pytest.mark.asyncio
async def test_multi_asset_aggregation(aml, mock_repo):
    # Already executed $45k equivalent (15 ETH @ $3000)
    async def side_effect(user_id, asset):
        if asset == "ETH":
            return Decimal("15")   # 15 ETH = $45,000
        return Decimal("0")
    mock_repo.get_daily_executed_sum.side_effect = side_effect

    # Try to withdraw $6k more (2 ETH)
    result = await aml.check_daily_limit("user-001", "ETH", Decimal("2"))
    assert result is False   # 45k + 6k = 51k > 50k limit
