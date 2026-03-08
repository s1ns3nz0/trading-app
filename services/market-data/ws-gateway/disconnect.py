"""
$disconnect handler — called when a client disconnects (clean or unclean).
Removes the connection record from DynamoDB.
"""
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

ddb = boto3.resource("dynamodb")
table = ddb.Table(os.environ["CONNECTIONS_TABLE"])


def handler(event: dict, context) -> dict:
    connection_id = event["requestContext"]["connectionId"]

    table.delete_item(Key={"connectionId": connection_id})
    logger.info("WS disconnected: %s", connection_id)
    return {"statusCode": 200}
