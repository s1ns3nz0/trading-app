import json
import boto3
from ..config import settings


class StepFnService:
    def __init__(self):
        self._client = boto3.client(
            "stepfunctions", region_name=settings.aws_region
        )

    async def start_execution(self, withdrawal_id: str) -> str:
        """Start execution; withdrawal_id as name = idempotency key."""
        resp = self._client.start_execution(
            stateMachineArn=settings.step_fn_arn,
            name=withdrawal_id,
            input=json.dumps({"withdrawalId": withdrawal_id}),
        )
        return resp["executionArn"]
