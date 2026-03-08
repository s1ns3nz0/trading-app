"""
Candle Builder Lambda — MSK triggered.

Consumes market.candles.1m.v1 Kafka topic and writes closed OHLCV bars
to DynamoDB.  Offset is committed only after a successful DynamoDB write
(handled by Lambda MSK trigger's bisect_batch_on_function_error = true).
"""
import base64
import json
import logging
import os
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

ddb = boto3.resource("dynamodb")
table = ddb.Table(os.environ["CANDLES_TABLE"])


def handler(event: dict, context) -> None:
    """
    Event shape (MSK trigger):
    {
      "records": {
        "market.candles.1m.v1-0": [
          { "topic": "...", "partition": 0, "offset": 42,
            "value": "<base64-encoded JSON>", ... }
        ]
      }
    }
    """
    records = event.get("records", {})
    written = 0
    errors = 0

    for topic_partition, messages in records.items():
        for msg in messages:
            try:
                payload = json.loads(base64.b64decode(msg["value"]).decode())
                _write_candle(payload)
                written += 1
            except (KeyError, ValueError) as e:
                logger.error("Malformed candle payload: %s | error=%s", msg.get("value", ""), e)
                errors += 1
            except ClientError:
                logger.exception("DynamoDB write failed for candle: %s", msg.get("value", ""))
                raise  # Re-raise so MSK trigger retries the batch

    logger.info("Candle Builder: written=%d errors=%d", written, errors)


def _write_candle(payload: dict) -> None:
    """
    Write one OHLCV candle to DynamoDB.

    PK = CANDLE#{symbol}#{interval}
    SK = openTime (Number)
    GSI1PK = SYMBOL#{symbol}
    GSI1SK = {interval}#{openTime}
    """
    symbol   = payload["symbol"]
    interval = payload["interval"]
    open_time = int(payload["openTime"])

    try:
        table.put_item(
            Item={
                "PK":        f"CANDLE#{symbol}#{interval}",
                "SK":        open_time,
                "GSI1PK":   f"SYMBOL#{symbol}",
                "GSI1SK":   f"{interval}#{open_time}",
                "open":      payload["open"],
                "high":      payload["high"],
                "low":       payload["low"],
                "close":     payload["close"],
                "volume":    payload["volume"],
                "closeTime": int(payload["closeTime"]),
                "symbol":    symbol,
                "interval":  interval,
            },
            # Idempotent: overwrite if same bar arrives twice (e.g. on retry)
            ConditionExpression="attribute_not_exists(SK) OR SK = :ot",
            ExpressionAttributeValues={":ot": open_time},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.info(
                "Candle already exists (idempotent): %s/%s/%s",
                symbol, interval, open_time,
            )
        else:
            raise
