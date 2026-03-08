"""
$default handler — routes subscribe/unsubscribe actions.
Stores subscription in DynamoDB and immediately pushes a Redis snapshot.

Client protocol:
  subscribe:    { "action": "subscribe",   "channel": "ticker|orderbook|trade", "symbol": "BTC-USDT" }
  unsubscribe:  { "action": "unsubscribe", "channel": "ticker|orderbook|trade", "symbol": "BTC-USDT" }
"""
import asyncio
import json
import logging
import os

import boto3
import redis.asyncio as aioredis
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

CONNECTIONS_TABLE = os.environ["CONNECTIONS_TABLE"]
REDIS_URL         = os.environ["REDIS_URL"]
API_GW_ENDPOINT   = os.environ["API_GW_ENDPOINT"]

ddb = boto3.resource("dynamodb")
table = ddb.Table(CONNECTIONS_TABLE)

# Lazy singleton for APIGW management client
_apigw = None


def _get_apigw():
    global _apigw
    if _apigw is None:
        _apigw = boto3.client(
            "apigatewaymanagementapi",
            endpoint_url=API_GW_ENDPOINT,
        )
    return _apigw


def handler(event: dict, context) -> dict:
    connection_id = event["requestContext"]["connectionId"]
    body = json.loads(event.get("body") or "{}")

    action  = body.get("action")
    channel = body.get("channel")           # ticker | orderbook | trade
    symbol  = (body.get("symbol") or "").upper()

    if not channel or not symbol:
        return {"statusCode": 400, "body": "Missing channel or symbol"}

    subscription_key = f"{channel}:{symbol}"

    if action == "subscribe":
        table.update_item(
            Key={"connectionId": connection_id},
            UpdateExpression="ADD subscriptions :s",
            ExpressionAttributeValues={":s": {subscription_key}},
        )
        # Push immediate snapshot so client doesn't wait for next tick
        asyncio.run(_push_snapshot(connection_id, channel, symbol))
        logger.info("Subscribe: conn=%s channel=%s symbol=%s", connection_id, channel, symbol)

    elif action == "unsubscribe":
        table.update_item(
            Key={"connectionId": connection_id},
            UpdateExpression="DELETE subscriptions :s",
            ExpressionAttributeValues={":s": {subscription_key}},
        )
        logger.info("Unsubscribe: conn=%s channel=%s symbol=%s", connection_id, channel, symbol)

    else:
        return {"statusCode": 400, "body": f"Unknown action: {action}"}

    return {"statusCode": 200}


async def _push_snapshot(connection_id: str, channel: str, symbol: str) -> None:
    """Fetch current data from Redis and push to client as an immediate snapshot."""
    r = await aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        data = None
        if channel == "ticker":
            raw = await r.hgetall(f"ticker:{symbol}")
            if raw:
                data = raw

        elif channel == "orderbook":
            raw_bids = await r.zrevrange(f"orderbook:{symbol}:bids", 0, 19, withscores=True)
            raw_asks = await r.zrange(f"orderbook:{symbol}:asks", 0, 19, withscores=True)
            data = {
                "bids": [{"price": str(score), "qty": json.loads(m)["qty"]} for m, score in raw_bids],
                "asks": [{"price": str(score), "qty": json.loads(m)["qty"]} for m, score in raw_asks],
            }

        if data:
            _get_apigw().post_to_connection(
                ConnectionId=connection_id,
                Data=json.dumps({"type": channel, "symbol": symbol, "data": data}),
            )
    except ClientError as e:
        if e.response["Error"]["Code"] == "GoneException":
            # Client disconnected during processing — clean up
            table.delete_item(Key={"connectionId": connection_id})
        else:
            logger.exception("APIGW post_to_connection failed")
    finally:
        await r.aclose()
