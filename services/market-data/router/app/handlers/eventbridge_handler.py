"""
EventBridge publisher for cross-account market data events.
Downstream consumers: SpotTrading (price validation), FuturesTrading (mark price),
RiskCompliance (exposure monitoring).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from ..config import settings

logger = logging.getLogger(__name__)

TOPIC_TO_DETAIL_TYPE = {
    "market.ticker.v1":     "MarketData.TickerUpdated",
    "market.orderbook.v1":  "MarketData.OrderBookUpdated",
    "market.trades.v1":     "MarketData.TradeExecuted",
}


class EventBridgePublisher:
    def __init__(self):
        self._client = boto3.client("events", region_name=settings.aws_region)

    async def publish(self, topic: str, payload: dict) -> None:
        detail_type = TOPIC_TO_DETAIL_TYPE.get(topic)
        if not detail_type:
            return  # candle events don't go to EventBridge

        entry = {
            "Source":       "com.tradingapp.market-data",
            "DetailType":   detail_type,
            "Detail":       json.dumps(payload),
            "EventBusName": settings.event_bus_name,
            "Time":         datetime.now(timezone.utc),
        }

        try:
            response = self._client.put_events(Entries=[entry])
            if response.get("FailedEntryCount", 0) > 0:
                logger.error("EventBridge put_events partial failure: %s", response["Entries"])
        except ClientError:
            logger.exception("EventBridge publish failed for topic=%s", topic)
            # Don't re-raise — EventBridge failure shouldn't block Redis write
