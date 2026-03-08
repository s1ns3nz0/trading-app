import json

import boto3

from ..config import settings


class StepFnService:
    def __init__(self):
        self._client = boto3.client(
            "stepfunctions", region_name=settings.aws_region
        )

    async def start_execution(self, deposit_id: str) -> str:
        """
        Start Step Functions execution. Returns execution ARN.
        Using deposit_id as name ensures idempotency:
        duplicate calls raise ExecutionAlreadyExists.
        """
        resp = self._client.start_execution(
            stateMachineArn=settings.step_fn_arn,
            name=deposit_id,
            input=json.dumps({"depositId": deposit_id}),
        )
        return resp["executionArn"]
