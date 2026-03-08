import json
from datetime import datetime, timezone

import boto3

from ..config import settings
from ..models.domain import DepositRequest


class EventBridgeProducer:
    def __init__(self):
        self._client = boto3.client("events", region_name=settings.aws_region)

    async def publish_deposit_confirmed(self, deposit: DepositRequest) -> None:
        credited_at = (
            deposit.credited_at.isoformat()
            if deposit.credited_at
            else datetime.now(timezone.utc).isoformat()
        )
        self._client.put_events(
            Entries=[
                {
                    "Source": "finance.deposit",
                    "DetailType": "DepositConfirmed",
                    "EventBusName": settings.eventbridge_bus_name,
                    "Detail": json.dumps(
                        {
                            "deposit_id": deposit.id,
                            "user_id": deposit.user_id,
                            "asset": deposit.asset,
                            "amount": str(deposit.amount),
                            "credited_at": credited_at,
                        }
                    ),
                }
            ]
        )
