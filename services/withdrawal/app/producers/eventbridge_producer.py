import json
from datetime import datetime, timezone
import boto3
from ..config import settings
from ..models.domain import WithdrawalRequest


class EventBridgeProducer:
    def __init__(self):
        self._client = boto3.client("events", region_name=settings.aws_region)

    async def publish_withdrawal_executed(self, w: WithdrawalRequest) -> None:
        executed_at = (
            w.executed_at.isoformat()
            if w.executed_at
            else datetime.now(timezone.utc).isoformat()
        )
        self._client.put_events(
            Entries=[{
                "Source":       "finance.withdrawal",
                "DetailType":   "WithdrawalExecuted",
                "EventBusName": settings.eventbridge_bus_name,
                "Detail": json.dumps({
                    "withdrawal_id": w.id,
                    "user_id":       w.user_id,
                    "asset":         w.asset,
                    "amount":        str(w.amount),
                    "tx_hash":       w.tx_hash,
                    "executed_at":   executed_at,
                }),
            }]
        )
