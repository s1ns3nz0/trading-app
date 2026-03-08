# Plan: market-data-service

> **Feature**: market-data-service
> **Created**: 2026-03-08
> **Phase**: Plan
> **Level**: Enterprise
> **Parent Platform**: trading-platform (archived 2026-03)

---

## Executive Summary

| Perspective | Detail |
|-------------|--------|
| **Problem** | The frontend trading UI has no live data — charts show loading spinners, order books are empty, and tickers display nothing because no service ingests real-time price feeds from exchanges or streams them to clients. |
| **Solution** | Build the MarketData bounded context: an ECS Fargate ingestion layer consuming exchange WebSocket feeds → MSK Kafka for fan-out → Redis for sub-millisecond read cache → API Gateway WebSocket API for browser push, with DynamoDB for OHLCV candle history. |
| **Function / UX Effect** | Users see live candlestick charts updating in real-time, order book depth bars changing tick-by-tick, and a 24h ticker strip reflecting current prices — all without polling, with <100ms end-to-end latency from exchange to browser. |
| **Core Value** | Decoupled, horizontally-scalable market data pipeline where exchange feed ingestion, storage, and client delivery are independent concerns — allowing any downstream service (SpotTrading order validation, RiskCompliance position limits, Notification price alerts) to consume canonical market data via Kafka without coupling to the exchange API directly. |

---

## 1. Overview

### 1.1 Background

The MarketData domain is a **Supporting domain** in the DDD hierarchy — it does not generate business value itself but enables all Core domains (SpotTrading, FuturesTrading, RiskCompliance) to function correctly. Without live market data:

- SpotTrading cannot validate order prices against market
- FuturesTrading cannot calculate mark price for liquidations
- Frontend shows no real-time charts or tickers
- RiskCompliance cannot monitor position exposure vs market price

### 1.2 Goals

| ID | Goal | Priority |
|----|------|----------|
| G-01 | Ingest real-time ticker, order book, and trade feed from Binance WebSocket API | Must |
| G-02 | Publish all market events to MSK Kafka for fan-out to downstream consumers | Must |
| G-03 | Cache live order book and ticker in Redis for sub-millisecond read latency | Must |
| G-04 | Stream live data to browser clients via API Gateway WebSocket | Must |
| G-05 | Store OHLCV candle data in DynamoDB for chart history (REST API) | Must |
| G-06 | REST API for historical candles, current ticker, and order book snapshot | Must |
| G-07 | Anti-Corruption Layer (ACL) wrapping Binance API — domain model is exchange-agnostic | Must |
| G-08 | Support multiple trading pairs dynamically (no hardcoded symbol lists) | Should |
| G-09 | Graceful degradation — cached data served when exchange connection drops | Should |
| G-10 | Multi-exchange support (Binance primary, OKX/Bybit as fallback) | Could |

### 1.3 Non-Goals

- Order matching (belongs to SpotTrading/FuturesTrading)
- Price prediction or analytics (belongs to RiskCompliance)
- User-specific data (belongs to Identity/Portfolio)
- Fiat currency pricing (belongs to Finance)

---

## 2. Domain Model

### 2.1 Bounded Context: MarketData

```
MarketData Domain
│
├── Entities
│   ├── Ticker          — 24h price stats for a symbol (lastPrice, priceChange, volume, high, low)
│   ├── OrderBookLevel  — single bid or ask level (price, quantity)
│   ├── OrderBook       — aggregated bid/ask depth (top N levels) for a symbol
│   ├── Trade           — individual trade execution (price, qty, buyerMaker, timestamp)
│   └── Candle          — OHLCV bar for a symbol + interval (1m, 5m, 1h, 1d)
│
├── Value Objects
│   ├── Symbol          — normalized trading pair (e.g. "BTC-USDT", not "BTCUSDT")
│   └── Interval        — candlestick interval enum (1m | 5m | 15m | 1h | 4h | 1d)
│
└── Domain Events (published to Kafka)
    ├── MarketData.TickerUpdated      { symbol, ticker, timestamp }
    ├── MarketData.OrderBookUpdated   { symbol, bids, asks, timestamp }
    └── MarketData.TradeExecuted      { symbol, trade, timestamp }
```

### 2.2 Anti-Corruption Layer (ACL)

The ACL translates Binance-specific wire format into the canonical domain model. No Binance types leak beyond the ACL boundary.

```
Binance WebSocket Stream                   MarketData Domain Model
─────────────────────────                  ──────────────────────────
{                                          Ticker {
  "s": "BTCUSDT",               →ACL→       symbol: "BTC-USDT",
  "c": "67432.10",                          lastPrice: 67432.10,
  "P": "2.45",                              priceChangePercent: 2.45,
  "v": "14321.5",                           volume: 14321.5,
  "h": "68100.00",                          high: 68100.00,
  "l": "65800.00"                           low: 65800.00
}                                         }
```

---

## 3. Architecture

### 3.1 Data Flow

```
                      ┌─────────────────────────────────────────────────────┐
                      │  marketdata-prod AWS Account (10.1.0.0/16)          │
                      │                                                       │
  Binance WSS ────────►  Feed Ingester        ──Kafka──►  Event Router       │
  (wss://stream.      │  (ECS Fargate)         (MSK)    │  (ECS Fargate)     │
   binance.com)       │  ACL translation               ├──► Redis Writer     │
                      │  reconnect + backpressure       │    (ElastiCache)    │
                      │                                 ├──► Candle Builder   │
                      │                                 │    (Lambda)         │
                      │                                 └──► EventBridge Pub  │
                      │                                      (cross-account)  │
                      │                                                       │
  Browser ◄───────────│  WS Gateway          ◄──Redis── Live Cache           │
  (WebSocket)         │  (API GW WebSocket               (ticker, orderbook) │
                      │   + Lambda $connect               sub-ms reads       │
                      │   + Lambda $default)                                  │
                      │                                                       │
  Browser ◄───────────│  REST API            ◄──DynamoDB─ Candle History      │
  (HTTP/REST)         │  (API GW HTTP + ECS)              (OHLCV storage)    │
                      │                                                       │
                      └─────────────────────────────────────────────────────┘
                                        │
                         EventBridge cross-account events
                                        │
                      ┌─────────────────┼──────────────────┐
                      ▼                 ▼                   ▼
              spottrading-prod  futurestrading-prod  riskcompliance-prod
              (price validation) (mark price calc)   (exposure monitoring)
```

### 3.2 Component Breakdown

| Component | Runtime | Responsibility |
|-----------|---------|---------------|
| **Feed Ingester** | ECS Fargate (Python) | Connect to Binance WS, ACL translate, publish to Kafka |
| **Event Router** | ECS Fargate (Python) | Consume Kafka, fan-out to Redis + Candle Builder + EventBridge |
| **Redis Writer** | In-process (Event Router) | Write ticker/orderbook/trades to Redis hash/sorted set |
| **Candle Builder** | Lambda (Python) | Aggregate 1-minute raw trades into OHLCV, write to DynamoDB |
| **WS Gateway** | API Gateway WebSocket + Lambda | Manage client connections, push live data from Redis |
| **REST API** | API Gateway HTTP + ECS Fargate | `/market/candles`, `/market/ticker`, `/market/orderbook` |

### 3.3 AWS Infrastructure

| Resource | Spec | Purpose |
|----------|------|---------|
| **ECS Fargate** (ingester) | 0.5 vCPU / 1GB, 2 tasks | Exchange feed connection (1 primary + 1 hot standby) |
| **ECS Fargate** (router) | 1 vCPU / 2GB, 3 tasks | Kafka consumer, fan-out |
| **ECS Fargate** (REST API) | 0.5 vCPU / 1GB, 2 tasks | HTTP REST API server |
| **MSK Kafka** | `kafka.t3.small`, 3 brokers, 3 AZs | Market event streaming (durable, replayable) |
| **ElastiCache Redis** | `cache.r7g.large`, 1 shard, 1 replica | Live order book + ticker cache |
| **DynamoDB** | On-demand | OHLCV candle history (single-table) |
| **API GW WebSocket** | — | Client WebSocket connections |
| **Lambda** (WS handlers) | 512MB | `$connect`, `$disconnect`, `$default` handlers |
| **Lambda** (Candle Builder) | 512MB | Kafka-triggered candle aggregation |

---

## 4. Kafka Topic Design

| Topic | Partitions | Retention | Schema |
|-------|:---------:|----------|--------|
| `market.ticker.v1` | 16 (by symbol hash) | 24h | `{ symbol, lastPrice, priceChangePercent, volume, high, low, openTime, closeTime }` |
| `market.orderbook.v1` | 16 | 1h | `{ symbol, bids: [[price, qty]], asks: [[price, qty]], lastUpdateId }` |
| `market.trades.v1` | 32 | 24h | `{ symbol, price, qty, buyerMaker, tradeTime, tradeId }` |
| `market.candles.1m.v1` | 8 | 7d | `{ symbol, openTime, open, high, low, close, volume, closeTime, isClosed }` |

---

## 5. Redis Data Structures

| Key Pattern | Type | TTL | Content |
|-------------|------|-----|---------|
| `ticker:{symbol}` | Hash | 60s | All ticker fields |
| `orderbook:{symbol}:bids` | Sorted Set | 10s | `score=price, member=qty_json` (top 20) |
| `orderbook:{symbol}:asks` | Sorted Set | 10s | `score=price, member=qty_json` (top 20) |
| `trades:{symbol}` | List (LPUSH/LTRIM) | 300s | Last 50 trades as JSON |
| `ws:connections:{symbol}` | Set | — | API GW connection IDs subscribed to symbol |

---

## 6. DynamoDB Candle Table (Single-Table)

| Attribute | Key Role | Example |
|-----------|----------|---------|
| `PK` | Hash key | `CANDLE#BTC-USDT#1m` |
| `SK` | Range key | `1709856000000` (openTime ms) |
| `open`, `high`, `low`, `close`, `volume` | Attributes | OHLCV values (String for precision) |
| `closeTime` | Attribute | Unix ms |
| `GSI1PK` | GSI hash | `SYMBOL#BTC-USDT` |
| `GSI1SK` | GSI range | `1m#1709856000000` (for multi-interval queries) |

---

## 7. REST API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/market/ticker/{symbol}` | Current 24h ticker from Redis |
| `GET` | `/market/ticker` | All symbols ticker list |
| `GET` | `/market/orderbook/{symbol}?depth=20` | Order book snapshot from Redis |
| `GET` | `/market/trades/{symbol}?limit=50` | Recent trades from Redis |
| `GET` | `/market/candles/{symbol}?interval=1m&limit=200&startTime=` | OHLCV history from DynamoDB |
| `GET` | `/market/symbols` | Available trading pairs |

---

## 8. WebSocket API Protocol

### Client → Server
```json
{ "action": "subscribe", "channel": "ticker", "symbol": "BTC-USDT" }
{ "action": "subscribe", "channel": "orderbook", "symbol": "BTC-USDT" }
{ "action": "unsubscribe", "channel": "ticker", "symbol": "BTC-USDT" }
```

### Server → Client (push)
```json
{ "type": "ticker", "symbol": "BTC-USDT", "data": { "lastPrice": "67432.10", ... } }
{ "type": "orderbook", "symbol": "BTC-USDT", "data": { "bids": [...], "asks": [...] } }
{ "type": "trade", "symbol": "BTC-USDT", "data": { "price": "67435.00", "qty": "0.012", ... } }
```

---

## 9. Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|------------|
| R-01 | Binance WS disconnects (rate limits, IP bans) | High | High | Exponential backoff, IP rotation via NAT GW, fallback to REST polling |
| R-02 | Kafka consumer lag during high volatility bursts | Medium | Medium | Monitor consumer lag metric, auto-scale Event Router tasks |
| R-03 | Redis eviction under memory pressure | Low | High | maxmemory-policy allkeys-lru, monitor eviction rate, scale up |
| R-04 | DynamoDB hot partition (one symbol dominates) | Medium | Medium | Prefix sharding on PK, use on-demand billing |
| R-05 | API Gateway WebSocket connection limit (10k default) | Medium | Medium | Request limit increase; use SNS fan-out for >10k connections |
| R-06 | Candle data loss during Lambda cold start | Low | Medium | Kafka offset commit after successful DynamoDB write |

---

## 10. Success Metrics

| Metric | Target |
|--------|--------|
| End-to-end latency (Binance → browser) | < 100ms p99 |
| Redis hit rate for ticker/orderbook reads | > 99% |
| Kafka consumer lag | < 1,000 messages |
| Candle data completeness (no missing bars) | > 99.9% |
| WS client push latency | < 50ms p95 |
| Feed ingester uptime | > 99.9% |

---

## 11. Implementation Phases

| Phase | Scope | Deliverable |
|-------|-------|-------------|
| **Step 1** | Terraform: `infra/environments/prod/market-data/` using account-factory | VPC, ECS cluster, MSK, Redis, DynamoDB, API GW WebSocket |
| **Step 2** | Feed Ingester service: Binance WS → ACL → Kafka producer | `services/market-data/ingester/` |
| **Step 3** | Event Router service: Kafka consumer → Redis + EventBridge | `services/market-data/router/` |
| **Step 4** | Candle Builder Lambda: Kafka trigger → DynamoDB write | `services/market-data/candle-builder/` |
| **Step 5** | REST API service: ticker, orderbook, candles endpoints | `services/market-data/api/` |
| **Step 6** | WS Gateway Lambdas: connect/disconnect/default handlers | `services/market-data/ws-gateway/` |
| **Step 7** | Frontend integration: wire `useOrderBook`, `useTicker`, `PriceChart` to real endpoints | `apps/web/src/` (already has hooks, just needs `.env.local` pointing to real service) |

---

## 12. Next Steps

- [ ] Run `/pdca design market-data-service` to create detailed technical design
- [ ] Confirm Binance API key availability and rate limit tier
- [ ] Decide initial symbol list (BTC-USDT, ETH-USDT, SOL-USDT, BNB-USDT — matches `generateStaticParams` in frontend)
- [ ] Confirm MSK Kafka version (recommend 3.7.x for KRaft mode — no ZooKeeper)
