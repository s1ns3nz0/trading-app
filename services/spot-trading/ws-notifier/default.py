"""
Lambda: $default route handler for API GW WebSocket.
Handles subscribe/unsubscribe actions.
Listens to Redis pub/sub and pushes messages to connected clients.
"""
from __future__ import annotations

import json
import os

import boto3
import redis

REDIS_URL         = os.environ["REDIS_URL"]
APIGW_ENDPOINT    = os.environ["APIGW_ENDPOINT"]
CONNECTIONS_TABLE = os.environ["CONNECTIONS_TABLE"]

_apigw  = None
_redis  = None
_dynamo = None


def _get_apigw():
    global _apigw
    if _apigw is None:
        _apigw = boto3.client("apigatewaymanagementapi", endpoint_url=APIGW_ENDPOINT)
    return _apigw


def _get_redis():
    global _redis
    if _redis is None:
        _redis = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def _get_dynamo():
    global _dynamo
    if _dynamo is None:
        _dynamo = boto3.resource("dynamodb").Table(CONNECTIONS_TABLE)
    return _dynamo


def handler(event, context):
    connection_id = event["requestContext"]["connectionId"]
    body          = json.loads(event.get("body") or "{}")
    action        = body.get("action")

    if action == "subscribe":
        channel = body.get("channel")         # "orders" or "orderbook"
        subject = body.get("userId") or body.get("symbol", "")
        redis_channel = f"ws:{channel}:{subject}"

        # Store subscription in DynamoDB for resilience across Lambda cold starts
        _get_dynamo().update_item(
            Key={"connectionId": connection_id},
            UpdateExpression="ADD subscriptions :s",
            ExpressionAttributeValues={":s": {redis_channel}},
        )

        # Push one pending message from channel if available
        r      = _get_redis()
        pubsub = r.pubsub()
        pubsub.subscribe(redis_channel)
        for msg in pubsub.listen():
            if msg["type"] == "message":
                _push(connection_id, msg["data"])
                break
        pubsub.unsubscribe()

    elif action == "unsubscribe":
        channel = body.get("channel")
        subject = body.get("userId") or body.get("symbol", "")
        redis_channel = f"ws:{channel}:{subject}"

        _get_dynamo().update_item(
            Key={"connectionId": connection_id},
            UpdateExpression="DELETE subscriptions :s",
            ExpressionAttributeValues={":s": {redis_channel}},
        )

    return {"statusCode": 200}


def _push(connection_id: str, data: str) -> None:
    try:
        _get_apigw().post_to_connection(
            ConnectionId=connection_id,
            Data=data.encode(),
        )
    except _get_apigw().exceptions.GoneException:
        # Stale connection — clean up
        _get_dynamo().delete_item(Key={"connectionId": connection_id})
