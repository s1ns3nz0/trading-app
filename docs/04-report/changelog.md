# Trading App - Change Log

## [2026-03-08] - spot-trading-service Completion

### Added
- **SpotTrading Bounded Context**: Core domain for order submission and matching
  - Price-time priority matching engine (heap-based order book)
  - LIMIT/MARKET order types with GTC/IOC/FOK time-in-force
  - Pessimistic locking (SELECT FOR UPDATE) to prevent double-spend race conditions
  - Anti-corruption layer for market data consumption (Binance decoupling)
- **REST API** (8 endpoints under `/spot`)
  - POST /spot/orders: submit LIMIT/MARKET orders
  - DELETE /spot/orders/{orderId}: cancel open orders
  - GET /spot/orders, /spot/trades, /spot/positions: query endpoints
  - GET /spot/orderbook/{symbol}: live order book snapshot
  - GET /health: service health with engine status
- **WebSocket Real-Time Updates**: order status via Redis pub/sub + API Gateway + Lambda
- **PostgreSQL Schema** (3 tables)
  - `orders`: order history with LIMIT/MARKET type, status (PENDING/OPEN/PARTIAL/FILLED/CANCELLED/REJECTED)
  - `trades`: matched executions with buyer/seller fees
  - `positions`: user asset balances (available/locked) with SELECT FOR UPDATE for atomicity
- **Kafka Integration** (3 topics with acks=all durability)
  - spot.orders.v1: order lifecycle events
  - spot.trades.v1: trade executions (consumed by notification-service, risk-compliance-service)
  - spot.positions.v1: balance updates
- **Supported Trading Pairs**: BTC-USDT, ETH-USDT, SOL-USDT, BNB-USDT
- **Infrastructure as Code** (Terraform)
  - Aurora PostgreSQL (db.r6g.large, Multi-AZ writer+reader)
  - ElastiCache Redis (cache.r7g.medium) for order book cache + WebSocket pub/sub
  - API Gateway WebSocket with Lambda handlers (connect/disconnect/subscribe)
  - DynamoDB ws_connections table for subscription tracking
  - Security groups + IAM roles with least-privilege
- **Kubernetes Manifests**
  - order-api Deployment (2 replicas, m6i.large, FastAPI)
  - matching-engine StatefulSet (1 replica, c6i.xlarge, Python matching)
  - HPA: auto-scale 2-10 replicas on CPU/memory thresholds
- **Fee Structure**: 0.10% maker fee, 0.15% taker fee (deducted atomically on trade)
- **Performance SLOs**: Order submission <50ms p99, matching <10ms p99, Kafka publish <100ms

### Changed
- **Design-to-Implementation Alignment**: 95.5% match rate (135/142 checkpoints passing)
  - 16 gaps identified: 8 harmless/improvements, 2 design doc bugs (fixed in implementation), 2 medium (matched architecture decisions), 4 frontend integration (not backend blocker)
  - Zero iterations required (passed on first Check phase)

### Fixed
- **apply_trade() User ID Bug** (Design Doc Fix)
  - Design doc incorrectly passed trade.buy_order_id (order UUID) as buyer_id
  - Implementation correctly resolves actual user_id via database lookup

### Infrastructure
- Multi-AZ Aurora PostgreSQL 16.2 with read replicas for scaling
- ElastiCache Redis with automatic failover for order book snapshot/pub-sub
- Kubernetes StatefulSet ensures matching engine pod affinity (consistent ordering)
- Alembic migrations for reproducible schema versioning

### Observability
- `/health` endpoint exposes engine status (running, rebuild in progress)
- CloudWatch Logs for all Lambda functions + EKS pods
- Ready for Prometheus metrics (order latency, matching latency, Kafka publish latency)

### Documentation
- Complete PDCA cycle: [Plan](../01-plan/features/spot-trading-service.plan.md) → [Design](../02-design/features/spot-trading-service.design.md) → [Analysis](../03-analysis/spot-trading-service.analysis.md) → [Report](features/spot-trading-service.report.md)
- 6 production risks documented and mitigated
- All 37 implementation files delivered

### Known Limitations / Deferred
- Frontend hook (useOrders) changed from useReducer to Zustand store — architectural decision by frontend team, not backend blocker
- WebSocket message type naming inconsistency ("orderUpdate" vs "order_update") — frontend to fix in integration
- Matching engine runs embedded in FastAPI app (port 8001) instead of dedicated process — functionally equivalent but differs from design

### Next Steps
- Production deployment to staging environment
- Load testing: k6 with 100 concurrent users, verify <50ms order latency p99
- Integrate downstream services: notification-service (trade alerts), risk-compliance-service (position limits)
- Frontend team: align useOrders hook with backend contract
- Multi-exchange support in v1.1 (OKX, Bybit)

---

## [2026-03-08] - market-data-service Completion (Previous)

[See archived report: docs/archive/2026-03/market-data-service/]

### Added
- Live market data feed from Binance WebSocket
- Kafka topics: market.ticker.v1, market.orderbook.v1, market.trades.v1
- Redis cache for price snapshots (60s TTL for ticker, 10s for order book)
- Anti-Corruption Layer pattern for exchange format isolation
- 4 supported symbols: BTC-USDT, ETH-USDT, SOL-USDT, BNB-USDT

### Result
- 90.5% design match rate (120.5/134 checkpoints)
- 1 iteration cycle (Act-1: resolved 7 major gaps)
- Metrics: <100ms end-to-end latency, 99.7% Redis hit rate, 99.95% feed completeness
