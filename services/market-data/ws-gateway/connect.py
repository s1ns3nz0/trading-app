"""
$connect handler — called when a client establishes a WebSocket connection.
Stores connectionId in DynamoDB with a TTL (2 hours).
"""
import logging
import os
import time

import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

ddb = boto3.resource("dynamodb")
table = ddb.Table(os.environ["CONNECTIONS_TABLE"])

TTL_SECONDS = 7200  # 2 hours


def handler(event: dict, context) -> dict:
    connection_id = event["requestContext"]["connectionId"]

    table.put_item(
        Item={
            "connectionId": connection_id,
            "connectedAt":  int(time.time() * 1000),
            "subscriptions": set(),   # DynamoDB Set type
            "ttl": int(time.time()) + TTL_SECONDS,
        }
    )
    logger.info("WS connected: %s", connection_id)
    return {"statusCode": 200}
