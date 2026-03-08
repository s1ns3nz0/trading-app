"""
Lambda: $disconnect route — remove connectionId from DynamoDB.
"""
from __future__ import annotations

import os

import boto3

CONNECTIONS_TABLE = os.environ["CONNECTIONS_TABLE"]
_dynamo = None


def _get_dynamo():
    global _dynamo
    if _dynamo is None:
        _dynamo = boto3.resource("dynamodb").Table(CONNECTIONS_TABLE)
    return _dynamo


def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    _get_dynamo().delete_item(Key={"connectionId": connection_id})
    return {"statusCode": 200}
