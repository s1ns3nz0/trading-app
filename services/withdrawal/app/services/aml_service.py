from decimal import Decimal
from ..models.domain import DAILY_LIMIT_USD, USD_RATES
from ..repositories.withdrawal_repo import WithdrawalRepository


class AMLService:
    def __init__(self, repo: WithdrawalRepository) -> None:
        self._repo = repo

    def usd_equivalent(self, asset: str, amount: Decimal) -> Decimal:
        rate = USD_RATES.get(asset, Decimal("1"))
        return amount * rate

    async def check_daily_limit(
        self, user_id: str, asset: str, amount: Decimal
    ) -> bool:
        """
        Returns True if withdrawal is within AML daily limit.
        Sums all EXECUTED withdrawals (any asset) in last 24h as USD equivalent.
        """
        # Sum existing daily USD-equivalent for all assets
        existing_usd = Decimal("0")
        for a in ("ETH", "BTC", "USDT", "USD"):
            asset_sum = await self._repo.get_daily_executed_sum(user_id, a)
            existing_usd += self.usd_equivalent(a, asset_sum)

        new_usd = self.usd_equivalent(asset, amount)
        return (existing_usd + new_usd) <= DAILY_LIMIT_USD
