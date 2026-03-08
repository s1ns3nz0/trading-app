"""GET /market/candles/{symbol}?interval=1m&limit=200&startTime="""
from fastapi import APIRouter, HTTPException, Query, Request
from boto3.dynamodb.conditions import Key

from ..schemas import CandleResponse

router = APIRouter()

VALID_INTERVALS = {"1m", "5m", "15m", "1h", "4h", "1d"}


@router.get("/candles/{symbol}", response_model=list[CandleResponse])
async def get_candles(
    symbol: str,
    request: Request,
    interval: str = Query(default="1m"),
    limit: int = Query(default=200, ge=1, le=1000),
    start_time: int = Query(default=None, alias="startTime"),
):
    """OHLCV history from DynamoDB. PK = CANDLE#{symbol}#{interval}, SK = openTime."""
    if interval not in VALID_INTERVALS:
        raise HTTPException(status_code=400, detail=f"Invalid interval. Valid: {VALID_INTERVALS}")

    table = request.app.state.ddb_table
    sym = symbol.upper()
    pk = f"CANDLE#{sym}#{interval}"

    key_cond = Key("PK").eq(pk)
    if start_time:
        key_cond &= Key("SK").gte(start_time)

    response = table.query(
        KeyConditionExpression=key_cond,
        ScanIndexForward=True,   # ascending by openTime
        Limit=limit,
    )

    candles = [
        {
            "openTime":  item["SK"],
            "open":      item["open"],
            "high":      item["high"],
            "low":       item["low"],
            "close":     item["close"],
            "volume":    item["volume"],
            "closeTime": item["closeTime"],
        }
        for item in response.get("Items", [])
    ]

    if not candles:
        raise HTTPException(status_code=404, detail=f"No candle data for {symbol}/{interval}")

    return candles
