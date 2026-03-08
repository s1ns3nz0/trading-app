# Plan: spot-trading-service

> **Feature**: spot-trading-service
> **Created**: 2026-03-08
> **Phase**: Plan
> **Level**: Enterprise
> **Parent Platform**: trading-platform (archived 2026-03)
> **Depends On**: market-data-service (archived), identity-service (implemented)

---

## Executive Summary

| Perspective | Detail |
|-------------|--------|
| **Problem** | Users can view live market data but cannot place orders — there is no order submission, validation, or matching engine, making the platform read-only and commercially non-functional. |
| **Solution** | Build the SpotTrading bounded context: a FastAPI order API behind the JWT authorizer → Redis order book cache → price-time priority matching engine (EKS Python pod) → PostgreSQL for persistence → MSK Kafka for trade event fan-out to downstream services. |
| **Function / UX Effect** | Users can place limit and market orders that execute immediately against resting orders; they see real-time order status via WebSocket, filled trade confirmations, and a live open-orders list — completing the full spot trading loop. |
| **Core Value** | The Core domain of the platform — SpotTrading generates revenue through maker/taker fees and is the primary reason users open accounts; all other services (MarketData, RiskCompliance, Notification) exist to support its correct and fast execution. |

---

## 1. Overview

### 1.1 Background

SpotTrading is the **Core domain** in the DDD hierarchy — it directly generates business value and is the primary differentiator of the platform. With MarketData providing live price feeds and Identity providing authentication, the system is ready for the trading engine layer.

SpotTrading boundary responsibilities:
- Accept and validate order submissions from authenticated users
- Maintain an in-memory order book per trading pair (BTC-USDT, ETH-USDT, SOL-USDT, BNB-USDT)
- Execute price-time priority matching between buy and sell orders
- Persist all orders and trades to PostgreSQL
- Publish `SpotTrading.TradeExecuted` and `SpotTrading.OrderFilled` events to Kafka for downstream consumers (RiskCompliance, Notification, Portfolio)

### 1.2 Goals

| ID | Goal | Priority |
|----|------|----------|
| G-01 | Accept LIMIT and MARKET order submissions via REST API (authenticated) | Must |
| G-02 | Validate orders against live market data from Redis (price sanity, min/max qty) | Must |
| G-03 | Validate user balance via Position service before order acceptance | Must |
| G-04 | Maintain in-memory order book per symbol (bid/ask queues) | Must |
| G-05 | Execute price-time priority matching on order submission | Must |
| G-06 | Persist all orders and trades to PostgreSQL | Must |
| G-07 | Publish trade/fill events to MSK Kafka for downstream consumers | Must |
| G-08 | Real-time order status via WebSocket push (connected via API GW WS or Redis pub/sub) | Must |
| G-09 | Cancel open orders | Must |
| G-10 | Query user's open orders, order history, trade history | Must |
| G-11 | Anti-Corruption Layer for market data consumption (no direct Binance coupling) | Must |
| G-12 | Maker/taker fee calculation per trade | Should |
| G-13 | Partial fills (order partially matched, remainder stays on book) | Should |
| G-14 | POST-ONLY order type (reject if would be taker) | Could |
| G-15 | Order expiry (GTC, IOC, FOK) | Could |

### 1.3 Non-Goals

- Futures/perpetual trading (belongs to FuturesTrading)
- Fiat deposits/withdrawals (belongs to Finance)
- Portfolio analytics (belongs to Portfolio)
- Price prediction (belongs to RiskCompliance)
- User authentication (belongs to Identity)

---

## 2. Domain Model

### 2.1 Bounded Context: SpotTrading

```
SpotTrading Domain
│
├── Entities
│   ├── Order          — user intent to buy or sell (id, userId, symbol, side, type, price, qty, status)
│   ├── Trade          — matched execution (id, buyOrderId, sellOrderId, price, qty, fee, timestamp)
│   └── Position       — user's current balance per asset (userId, asset, available, locked)
│
├── Value Objects
│   ├── Symbol         — normalized trading pair "BTC-USDT"
│   ├── OrderSide      — BUY | SELL
│   ├── OrderType      — LIMIT | MARKET
│   ├── OrderStatus    — PENDING | OPEN | PARTIAL | FILLED | CANCELLED | REJECTED
│   └── TimeInForce    — GTC (Good Till Cancel) | IOC (Immediate or Cancel) | FOK (Fill or Kill)
│
└── Domain Events (published to Kafka)
    ├── SpotTrading.OrderCreated    { orderId, userId, symbol, side, type, price, qty }
    ├── SpotTrading.OrderFilled     { orderId, tradeId, filledQty, remainingQty, avgPrice }
    ├── SpotTrading.OrderCancelled  { orderId, userId, reason }
    └── SpotTrading.TradeExecuted   { tradeId, symbol, price, qty, buyUserId, sellUserId, fee }
```

### 2.2 Matching Engine Logic (Price-Time Priority)

```
Order Book per Symbol:
  bids: max-heap by price → [100.0 x 1.0 BTC, 99.5 x 2.0 BTC, ...]
  asks: min-heap by price → [101.0 x 0.5 BTC, 101.5 x 1.0 BTC, ...]

LIMIT BUY at 101.0:
  → Check top ask (101.0) ≤ bid price (101.0): MATCH
  → Execute trade at ask price (101.0), qty = min(bid_qty, ask_qty)
  → Emit TradeExecuted event
  → Update order statuses (FILLED or PARTIAL)
  → Remainder stays on book

MARKET BUY for 1.0 BTC:
  → Walk asks from lowest to highest until qty filled
  → Accept any price (no price constraint)
  → Partial fills until qty = 0 or book exhausted
```

### 2.3 Anti-Corruption Layer (Market Data)

```
MarketData (Kafka topic) → ACL → SpotTrading internal price cache

SpotTrading does NOT call Binance directly.
SpotTrading does NOT import MarketData domain types.
ACL translates Kafka payload → internal PriceSnapshot value object.

PriceSnapshot {
  symbol: str
  lastPrice: Decimal
  high24h: Decimal
  low24h: Decimal
  updatedAt: datetime
}

Order price sanity check: |order.price - snapshot.lastPrice| / snapshot.lastPrice ≤ 10%
```

---

## 3. Architecture

### 3.1 Data Flow

```
                    ┌──────────────────────────────────────────────────┐
                    │  spot-trading-prod AWS Account (10.2.0.0/16)     │
                    │                                                    │
 Browser ──────────►  Order API           ──PostgreSQL──► Order Store   │
 (JWT + REST)       │  (EKS pod / FastAPI)               (orders,       │
                    │  JWT auth via lambda-authorizer      trades,       │
                    │                                      positions)    │
                    │        │                                           │
                    │        ▼                                           │
                    │  Matching Engine     ──Redis────► Order Book Cache │
                    │  (EKS pod, Python)   (in-memory  (snapshot for    │
                    │  price-time priority  + Redis     REST reads)      │
                    │  matching heap        backup)                      │
                    │        │                                           │
                    │        ▼                                           │
                    │  Kafka Producer      ──MSK──────► market events   │
                    │  (trade/fill events)             (consumed by      │
                    │                                   risk, notif)    │
                    │                                                    │
 Browser ◄──────────  WS Notifier         ◄──Redis── pub/sub channels   │
 (order status)     │  (Redis sub → APIGW             order:{userId}    │
                    │   push)                                            │
                    └──────────────────────────────────────────────────┘
                                       │
                        Kafka cross-account events
                                       │
               ┌───────────────────────┼──────────────────────┐
               ▼                       ▼                       ▼
       riskcompliance-prod    notification-prod         portfolio-prod
       (position limits)      (fill alerts)            (balance update)
```

### 3.2 Component Breakdown

| Component | Runtime | Responsibility |
|-----------|---------|----------------|
| **Order API** | EKS (FastAPI, 2 pods) | Auth, validation, order CRUD, REST endpoints |
| **Matching Engine** | EKS (Python, 2 pods) | In-memory order book, price-time matching |
| **Position Service** | In-process (Order API) | Balance check + lock on order submission |
| **WS Notifier** | Lambda | Subscribe to Redis pub/sub, push to API GW WebSocket |
| **Kafka Producer** | In-process (Matching Engine) | Publish SpotTrading domain events |
| **Market Data ACL** | Background task (Order API) | Consume `market.ticker.v1` Kafka → internal price cache |

### 3.3 AWS Infrastructure

| Resource | Spec | Purpose |
|----------|------|---------|
| **EKS** | EKS 1.31, c6i.xlarge (matching) + m6i.large (api) | Kubernetes for stateful matching engine |
| **Aurora PostgreSQL** | 16.2, db.r6g.large, 2 instances | Orders, trades, positions (ACID) |
| **ElastiCache Redis** | cache.r7g.medium, 1 shard | Order book snapshot, pub/sub for WS |
| **MSK Kafka** | Shared cluster (market-data account) or dedicated | SpotTrading domain events |
| **API GW WebSocket** | — | Client real-time order status |
| **Lambda** (WS handler) | 512MB | Redis pub/sub → APIGW push |
| **Lambda Authorizer** | Shared from identity-service | JWT validation |

---

## 4. PostgreSQL Schema

### 4.1 Orders Table

```sql
CREATE TABLE orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL,
    symbol          VARCHAR(20) NOT NULL,
    side            VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
    type            VARCHAR(6) NOT NULL CHECK (type IN ('LIMIT', 'MARKET')),
    status          VARCHAR(10) NOT NULL DEFAULT 'PENDING',
    price           NUMERIC(20, 8),                 -- NULL for MARKET orders
    orig_qty        NUMERIC(20, 8) NOT NULL,
    executed_qty    NUMERIC(20, 8) NOT NULL DEFAULT 0,
    avg_price       NUMERIC(20, 8),
    time_in_force   VARCHAR(3) NOT NULL DEFAULT 'GTC',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT orders_price_required CHECK (type = 'MARKET' OR price IS NOT NULL)
);

CREATE INDEX idx_orders_user_symbol ON orders (user_id, symbol, created_at DESC);
CREATE INDEX idx_orders_symbol_status ON orders (symbol, status) WHERE status IN ('OPEN', 'PARTIAL');
```

### 4.2 Trades Table

```sql
CREATE TABLE trades (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    symbol          VARCHAR(20) NOT NULL,
    buy_order_id    UUID NOT NULL REFERENCES orders(id),
    sell_order_id   UUID NOT NULL REFERENCES orders(id),
    price           NUMERIC(20, 8) NOT NULL,
    qty             NUMERIC(20, 8) NOT NULL,
    buyer_fee       NUMERIC(20, 8) NOT NULL DEFAULT 0,
    seller_fee      NUMERIC(20, 8) NOT NULL DEFAULT 0,
    executed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_trades_buy_order ON trades (buy_order_id);
CREATE INDEX idx_trades_sell_order ON trades (sell_order_id);
CREATE INDEX idx_trades_symbol_time ON trades (symbol, executed_at DESC);
```

### 4.3 Positions Table

```sql
CREATE TABLE positions (
    user_id         UUID NOT NULL,
    asset           VARCHAR(10) NOT NULL,
    available       NUMERIC(20, 8) NOT NULL DEFAULT 0,
    locked          NUMERIC(20, 8) NOT NULL DEFAULT 0,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, asset),
    CONSTRAINT positions_non_negative CHECK (available >= 0 AND locked >= 0)
);
```

---

## 5. REST API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/spot/orders` | Submit new order (LIMIT or MARKET) |
| `DELETE` | `/spot/orders/{orderId}` | Cancel open order |
| `GET` | `/spot/orders/{orderId}` | Get order detail |
| `GET` | `/spot/orders?symbol=&status=&limit=` | List user's orders |
| `GET` | `/spot/trades?symbol=&limit=` | User's trade history |
| `GET` | `/spot/positions` | User's asset balances |
| `GET` | `/spot/orderbook/{symbol}` | Snapshot of current order book (top 20) |
| `GET` | `/health` | Health check |

### 5.1 Submit Order Request/Response

```json
POST /spot/orders
{
  "symbol": "BTC-USDT",
  "side": "BUY",
  "type": "LIMIT",
  "price": "67500.00",
  "qty": "0.001",
  "timeInForce": "GTC"
}

Response 201:
{
  "orderId": "uuid",
  "status": "OPEN",
  "symbol": "BTC-USDT",
  "side": "BUY",
  "price": "67500.00",
  "origQty": "0.001",
  "executedQty": "0.000",
  "createdAt": "2026-03-08T12:00:00Z"
}
```

---

## 6. WebSocket Protocol

### Client → Server
```json
{ "action": "subscribe", "channel": "orders", "userId": "<from JWT>" }
{ "action": "subscribe", "channel": "orderbook", "symbol": "BTC-USDT" }
```

### Server → Client (push)
```json
{ "type": "orderUpdate", "data": { "orderId": "...", "status": "FILLED", "executedQty": "0.001" } }
{ "type": "tradeExecuted", "data": { "tradeId": "...", "price": "67500", "qty": "0.001" } }
```

---

## 7. Kafka Topics

| Topic | Partitions | Retention | Schema |
|-------|:----------:|----------|--------|
| `spot.orders.v1` | 16 (by userId hash) | 7d | `{ orderId, userId, symbol, side, type, price, qty, status, timestamp }` |
| `spot.trades.v1` | 16 (by symbol hash) | 30d | `{ tradeId, symbol, price, qty, buyUserId, sellUserId, buyFee, sellFee, executedAt }` |
| `spot.positions.v1` | 8 (by userId hash) | 7d | `{ userId, asset, available, locked, updatedAt }` |

---

## 8. Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|------------|
| R-01 | Race condition on position balance (double-spend) | High | Critical | Pessimistic lock in PostgreSQL (`SELECT FOR UPDATE`) on position row |
| R-02 | Matching engine OOM on deep order book | Low | High | Cap order book depth at 1,000 levels per side; Redis overflow |
| R-03 | Matching engine pod restart loses in-memory book | Medium | High | Rebuild from PostgreSQL `OPEN/PARTIAL` orders on startup |
| R-04 | Kafka producer failure causes trade event loss | Low | High | Synchronous Kafka send with acks=all before committing DB |
| R-05 | Price sanity check too tight during high volatility | Medium | Medium | Configurable threshold (default 10%), disable for MARKET orders |
| R-06 | EKS pod autoscaling with shared order book state | Medium | High | Single matching engine pod per symbol; stateless order API pods |

---

## 9. Fee Structure

| Role | Fee | Calculation |
|------|-----|-------------|
| Maker (resting order) | 0.10% | `trade.qty × trade.price × 0.001` |
| Taker (aggressive order) | 0.15% | `trade.qty × trade.price × 0.0015` |

Fee deducted from received asset (buyer pays in quote asset, seller pays in base asset).

---

## 10. Success Metrics

| Metric | Target |
|--------|--------|
| Order submission latency (p99) | < 50ms |
| Order matching latency (p99) | < 10ms |
| Trade event Kafka publish latency | < 100ms |
| PostgreSQL position update (p99) | < 20ms |
| Order book depth (per symbol) | ≥ 100 levels |
| Throughput | ≥ 1,000 orders/sec per symbol |

---

## 11. Implementation Phases

| Phase | Scope | Deliverable |
|-------|-------|-------------|
| **Step 1** | Terraform: `infra/environments/prod/spot-trading/` extend existing IaC | EKS cluster, Aurora PostgreSQL, Redis, API GW WS |
| **Step 2** | PostgreSQL schema migrations | `services/spot-trading/migrations/` (Alembic) |
| **Step 3** | Domain models (Order, Trade, Position, matching types) | `services/spot-trading/app/models/` |
| **Step 4** | Position service (balance lock/unlock, balance check) | `services/spot-trading/app/services/position_service.py` |
| **Step 5** | Matching engine (order book heap, price-time priority) | `services/spot-trading/app/matching/` |
| **Step 6** | Kafka producer (trade/fill events) | `services/spot-trading/app/producers/` |
| **Step 7** | Market data ACL (consume `market.ticker.v1` → PriceSnapshot) | `services/spot-trading/app/acl/` |
| **Step 8** | Order API (FastAPI, all REST endpoints) | `services/spot-trading/app/routers/` |
| **Step 9** | WS Notifier Lambda (Redis pub/sub → API GW push) | `services/spot-trading/ws-notifier/` |
| **Step 10** | Frontend integration: `useOrders` hook wired to real endpoint | `apps/web/src/hooks/useOrders.ts` update |

---

## 12. Next Steps

- [ ] Run `/pdca design spot-trading-service` to create detailed technical design
- [ ] Confirm Aurora PostgreSQL instance exists in spot-trading account (already provisioned in `infra/environments/prod/spot-trading/`)
- [ ] Decide matching engine concurrency model: single-threaded event loop per symbol vs actor model
- [ ] Confirm fee rates with business (default 0.10% maker / 0.15% taker)
- [ ] Confirm initial supported symbols (BTC-USDT, ETH-USDT, SOL-USDT, BNB-USDT — matches frontend `generateStaticParams`)
