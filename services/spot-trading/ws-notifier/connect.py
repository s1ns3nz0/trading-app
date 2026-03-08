"""
Lambda: $connect route — store connectionId and set TTL.
"""
from __future__ import annotations

import os
import time

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
    ttl = int(time.time()) + 3600 * 24  # 24h TTL

    _get_dynamo().put_item(Item={
        "connectionId":  connection_id,
        "subscriptions": set(),
        "connectedAt":   int(time.time()),
        "ttl":           ttl,
    })

    return {"statusCode": 200}
