from __future__ import annotations

import json
import logging
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status

from ..main import db_pool, engines, kafka_prod, market_acl, redis_client
from ..models.domain import Order, OrderSide, OrderStatus, OrderType, TimeInForce
from ..repositories.order_repo import OrderRepository
from ..repositories.position_repo import PositionRepository
from ..repositories.trade_repo import TradeRepository
from ..schemas import OrderResponse, SubmitOrderRequest

logger = logging.getLogger(__name__)
router = APIRouter()


def _order_to_response(o: Order) -> OrderResponse:
    return OrderResponse(
        orderId=o.id,
        userId=o.user_id,
        symbol=o.symbol,
        side=o.side.value,
        type=o.type.value,
        status=o.status.value,
        price=str(o.price) if o.price else None,
        origQty=str(o.orig_qty),
        executedQty=str(o.executed_qty),
        avgPrice=str(o.avg_price) if o.avg_price else None,
        timeInForce=o.time_in_force.value,
        createdAt=o.created_at,
        updatedAt=o.updated_at,
    )


def _get_user_id(request: Request) -> str:
    """Extract userId injected by Lambda Authorizer into request context header."""
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user_id


@router.post("/orders", response_model=OrderResponse, status_code=201)
async def submit_order(body: SubmitOrderRequest, request: Request):
    user_id = _get_user_id(request)

    if body.symbol not in engines:
        raise HTTPException(status_code=400, detail=f"Unsupported symbol: {body.symbol}")

    # Price sanity check for LIMIT orders (R-05)
    order_price: Optional[Decimal] = None
    if body.type == "LIMIT":
        if not body.price:
            raise HTTPException(status_code=400, detail="price is required for LIMIT orders")
        order_price = Decimal(body.price)
        if not market_acl.validate_price(body.symbol, order_price):
            raise HTTPException(status_code=400, detail="Order price deviates > 10% from market price")

    qty = Decimal(body.qty)
    symbol_parts = body.symbol.split("-")
    base_asset, quote_asset = symbol_parts[0], symbol_parts[1]

    order = Order(
        user_id=user_id,
        symbol=body.symbol,
        side=OrderSide(body.side),
        type=OrderType(body.type),
        price=order_price,
        orig_qty=qty,
        time_in_force=TimeInForce(body.timeInForce),
    )

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            pos_repo   = PositionRepository(conn)
            order_repo = OrderRepository(conn)
            trade_repo = TradeRepository(conn)

            # Pessimistic lock on position (R-01)
            if body.side == "BUY":
                lock_asset  = quote_asset
                # For LIMIT: lock price × qty. For MARKET: use best-ask estimate or reject
                lock_amount = (order_price or Decimal("0")) * qty
            else:
                lock_asset  = base_asset
                lock_amount = qty

            locked = await pos_repo.lock_for_order(user_id, lock_asset, lock_amount)
            if not locked:
                raise HTTPException(status_code=400, detail="Insufficient balance")

            # Submit to matching engine (synchronous, in-memory, single asyncio thread)
            engine = engines[body.symbol]
            result = engine.submit(order)

            # Persist new order
            await order_repo.insert(result.order)

            # Persist trades and settle positions atomically within this transaction
            for trade in result.trades:
                await trade_repo.insert(trade)

                # Determine buyer/seller user IDs from order table
                if trade.buy_order_id == result.order.id:
                    buyer_id  = user_id
                    # Lookup seller from the resting order (persisted earlier or in current tx)
                    seller_row = await conn.fetchrow("SELECT user_id FROM orders WHERE id=$1", trade.sell_order_id)
                    seller_id  = str(seller_row["user_id"]) if seller_row else user_id
                else:
                    seller_id = user_id
                    buyer_row  = await conn.fetchrow("SELECT user_id FROM orders WHERE id=$1", trade.buy_order_id)
                    buyer_id   = str(buyer_row["user_id"]) if buyer_row else user_id

                await pos_repo.apply_trade(
                    buyer_id=buyer_id,
                    seller_id=seller_id,
                    base_asset=base_asset,
                    quote_asset=quote_asset,
                    qty=trade.qty,
                    price=trade.price,
                    buyer_fee=trade.buyer_fee,
                    seller_fee=trade.seller_fee,
                )

            # Update resting orders modified by matching
            for trade in result.trades:
                # Find resting order (the one that is NOT the incoming order)
                resting_id = trade.sell_order_id if result.order.side == OrderSide.BUY else trade.buy_order_id
                if resting_id != result.order.id:
                    resting_row = await conn.fetchrow("SELECT * FROM orders WHERE id=$1", resting_id)
                    if resting_row:
                        # Recalculate from trade data stored in engine
                        await conn.execute(
                            """
                            UPDATE orders
                            SET executed_qty = executed_qty + $2,
                                status = CASE
                                  WHEN orig_qty - (executed_qty + $2) <= 0 THEN 'FILLED'
                                  ELSE 'PARTIAL'
                                END,
                                updated_at = NOW()
                            WHERE id = $1
                            """,
                            resting_id, str(trade.qty)
                        )

    # Publish events AFTER DB commit — acks=all guarantees durability (R-04)
    await kafka_prod.publish_order(result.order)
    for trade in result.trades:
        await kafka_prod.publish_trade(trade)

    # Push real-time order update to user via Redis pub/sub → WS Lambda
    response = _order_to_response(result.order)
    await redis_client.publish(
        f"ws:orders:{user_id}",
        json.dumps({"type": "orderUpdate", "data": response.model_dump(mode="json")}),
    )

    return response


@router.delete("/orders/{order_id}", response_model=OrderResponse)
async def cancel_order(order_id: str, request: Request):
    user_id = _get_user_id(request)

    async with db_pool.acquire() as conn:
        async with conn.transaction():
            order_repo = OrderRepository(conn)
            order      = await order_repo.get(order_id, user_id)

            if not order:
                raise HTTPException(status_code=404, detail="Order not found")
            if not order.is_resting:
                raise HTTPException(status_code=400, detail=f"Cannot cancel order in status {order.status}")

            # Cancel from in-memory engine
            if order.symbol in engines:
                engines[order.symbol].cancel(order_id)

            order.status = OrderStatus.CANCELLED
            await order_repo.update_status(order)

            # Release locked balance
            pos_repo = PositionRepository(conn)
            symbol_parts = order.symbol.split("-")
            base_asset, quote_asset = symbol_parts[0], symbol_parts[1]

            if order.side == OrderSide.BUY:
                release_asset  = quote_asset
                release_amount = order.remaining_qty * (order.price or Decimal("0"))
            else:
                release_asset  = base_asset
                release_amount = order.remaining_qty

            await pos_repo.release_lock(user_id, release_asset, release_amount)

    await kafka_prod.publish_order(order)

    response = _order_to_response(order)
    await redis_client.publish(
        f"ws:orders:{user_id}",
        json.dumps({"type": "orderUpdate", "data": response.model_dump(mode="json")}),
    )
    return response


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(order_id: str, request: Request):
    user_id = _get_user_id(request)
    async with db_pool.acquire() as conn:
        order = await OrderRepository(conn).get(order_id, user_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return _order_to_response(order)


@router.get("/orders", response_model=list[OrderResponse])
async def list_orders(
    request: Request,
    symbol: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
):
    user_id = _get_user_id(request)
    async with db_pool.acquire() as conn:
        order_list = await OrderRepository(conn).list_by_user(user_id, symbol, status, limit)
    return [_order_to_response(o) for o in order_list]
