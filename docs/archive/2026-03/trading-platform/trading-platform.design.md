# Design: trading-platform

> **Feature**: trading-platform
> **Created**: 2026-03-08
> **Phase**: Design
> **Level**: Enterprise
> **Plan Reference**: docs/01-plan/features/trading-platform.plan.md

---

## 1. System Architecture Overview

### 1.1 Full Stack Map

```
Browser (Next.js 15 — apps/web)
    │
    ├── HTTPS REST  →  AWS API Gateway → ALB → ECS/EKS service (per domain)
    └── WSS         →  AWS API Gateway WebSocket → ECS (MarketData service)

Cross-Account Event Flow:
    SpotTrading account  →  EventBridge  →  RiskCompliance account
    FuturesTrading account → EventBridge →  Notification account
    Finance account      →  EventBridge  →  Identity account

Infrastructure:
    network-prod account (Transit Gateway + Network Firewall)
    security-prod account (GuardDuty admin, SecurityHub aggregator)
    log-archive-prod account (S3 centralized logs)
```

### 1.2 Request Lifecycle

```
User → Next.js browser client
     → identityApi.ts          → identity-prod:8000  (auth/login → JWT)
     → spotTradingApi.ts       → spottrading-prod:8001 (order CRUD)
     → futuresTradingApi.ts    → futurestrading-prod:8002 (position mgmt)
     → financeApi.ts           → deposit-prod/withdrawal-prod:8003
     → WebSocket (MarketData)  → marketdata-prod:8443/ws

JWT validated at each service's API Gateway authorizer (Lambda)
No shared auth database — each service validates token signature via JWKS endpoint
```

---

## 2. Frontend Architecture

### 2.1 Application Structure

```
apps/web/src/
├── app/                      Next.js App Router
│   ├── layout.tsx            Root layout (Providers: QueryClient)
│   ├── page.tsx              → redirect /spot/BTC-USDT
│   ├── (auth)/               Route group — no Sidebar/Header
│   │   ├── layout.tsx        Centered card layout
│   │   ├── login/page.tsx    Email + password + optional TOTP
│   │   └── register/page.tsx Email + username + password
│   └── (trading)/            Route group — with Sidebar + Header
│       ├── layout.tsx        Sidebar + Header shell
│       ├── spot/[pair]/      Dynamic: BTC-USDT, ETH-USDT, …
│       ├── futures/[pair]/   Dynamic: BTC-USDT, ETH-USDT, …
│       ├── portfolio/        Balance table + open orders
│       ├── deposit/          Network selector + address QR
│       └── withdraw/         Network + fee calculator + form
│
├── components/
│   ├── trading/              Spot-specific
│   │   ├── OrderBook         Real-time bids/asks depth visualization
│   │   ├── OrderForm         Limit/Market/Stop-Limit, Buy/Sell, presets
│   │   ├── TradeHistory      Last 50 market trades via WebSocket
│   │   ├── PriceChart        TradingView lightweight-charts candlestick
│   │   └── MarketTicker      24h stats bar (price, change, H/L, volume)
│   ├── futures/              Futures-specific
│   │   ├── FuturesOrderForm  Long/Short, leverage, reduce-only
│   │   ├── LeverageSelector  Slider + presets (1x–125x), calls backend
│   │   └── PositionPanel     Open positions table with close button
│   ├── portfolio/
│   │   ├── BalanceTable      Asset balances with USDT valuation
│   │   └── OpenOrders        Cancel-able order table across all pairs
│   ├── finance/
│   │   ├── DepositForm       Asset/network picker → deposit address
│   │   └── WithdrawForm      Address + amount + fee breakdown
│   └── layout/
│       ├── Sidebar           Navigation + pair list
│       └── Header            Auth status + logout

├── hooks/
│   ├── useWebSocket          Auto-reconnect WS (max 5 retries, 3s interval)
│   ├── useOrderBook          Subscribes to WS orderbook channel
│   ├── useTicker             Subscribes to WS ticker channel
│   └── useOrders             REST fetch + WS order_update subscription

├── services/                 One file per domain
│   ├── api.ts                Base fetch wrapper (auth header injection, 401 handler)
│   ├── identityApi.ts        login, register, refreshToken, getMe, TOTP
│   ├── spotTradingApi.ts     ticker, orderbook, trades, placeOrder, cancelOrder, portfolio
│   ├── futuresTradingApi.ts  positions, leverage, marginMode, placeFuturesOrder
│   └── financeApi.ts         depositAddress, withdrawalFee, submitWithdrawal, history

└── stores/                   Zustand (persisted where applicable)
    ├── authStore             user, tokens, isAuthenticated (persisted)
    ├── tradingStore          ticker, orderBook, recentTrades, openOrders, positions, leverage
    └── portfolioStore        portfolio (balances + summary)
```

### 2.2 State Management Architecture

```
┌──────────────────────────────────────────────────────────┐
│                      Zustand Stores                       │
│                                                           │
│  authStore (persisted to localStorage)                    │
│  ├── user: User | null                                    │
│  ├── tokens: { accessToken, refreshToken, expiresIn }     │
│  └── isAuthenticated: boolean                             │
│                                                           │
│  tradingStore (in-memory, per session)                    │
│  ├── selectedPair: string                                 │
│  ├── ticker: Ticker | null          ← WS update           │
│  ├── orderBook: OrderBook | null    ← WS update           │
│  ├── recentTrades: Trade[]          ← WS append (max 50)  │
│  ├── openOrders: Order[]            ← REST + WS update    │
│  ├── positions: FuturesPosition[]   ← REST + WS update    │
│  ├── leverage: number               ← user preference     │
│  └── marginMode: 'cross'|'isolated' ← user preference     │
│                                                           │
│  portfolioStore (in-memory, REST-fetched)                 │
│  ├── portfolio: Portfolio | null                          │
│  └── lastFetchedAt: number | null                        │
└──────────────────────────────────────────────────────────┘

Data flow:
  REST call → service function → store.set()
  WebSocket message → hook handler → store.set()
  Component → useStore hook → re-renders reactively
```

### 2.3 WebSocket Protocol

```
Client connects to: wss://ws.marketdata.cryptotrade.internal/{channel}/{symbol}

Channels:
  /market/orderbook/{symbol}    → WsOrderBookMessage
  /market/ticker/{symbol}       → WsTickerMessage
  /market/trades/{symbol}       → WsTradeMessage
  /user/orders                  → WsOrderUpdateMessage  (authenticated)

Message envelope:
{
  "type": "orderbook" | "ticker" | "trade" | "order_update",
  "data": { ... }  // typed per channel
}

Auth for /user/orders: send after onopen:
{
  "type": "auth",
  "token": "<accessToken>"
}

Reconnection: exponential backoff (3s, 6s, 12s, 24s, 48s), max 5 attempts
```

### 2.4 Page Layouts

```
Spot Trading Page (/spot/[pair])
┌────────────────────────────────────────────────────────────────┐
│ MarketTicker (symbol, last price, 24h change, H/L, volume)     │
├─────────────────────────────┬──────────────┬───────────────────┤
│                             │              │                    │
│  PriceChart (flex-1)        │  OrderBook   │  OrderForm         │
│  lightweight-charts         │  (w-56)      │  (w-64)           │
│  candlestick, dark theme    │  bids/asks   │  buy/sell tabs    │
│                             │  depth bars  │  limit/market     │
├─────────────────────────────┤              │  presets 25-100%  │
│  OpenOrders (border-t)      │              ├───────────────────┤
│  cancel-able table          │              │  TradeHistory     │
└─────────────────────────────┴──────────────┴───────────────────┘

Futures Trading Page (/futures/[pair])
┌────────────────────────────────────────────────────────────────┐
│ MarketTicker                                                    │
├──────────────────────────────────┬──────────┬──────────────────┤
│ PriceChart                       │OrderBook │ FuturesOrderForm  │
│                                  │          │ leverage selector │
│                                  │          │ long/short        │
│                                  │          │ liq. price est.   │
├──────────────────────────────────┤          ├──────────────────┤
│ PositionPanel (max-h-200)        │          │ TradeHistory      │
│ open positions + close button    │          │                   │
└──────────────────────────────────┴──────────┴──────────────────┘
```

---

## 3. Domain Service Designs

### 3.1 Identity Service

**AWS Stack**: Lambda + API Gateway, DynamoDB (users), ElastiCache Redis (sessions/JWTs)

**API Contract**:
```
POST   /auth/register           → { user, tokens }
POST   /auth/login              → { user, tokens } | 401 TOTP_REQUIRED
POST   /auth/refresh            → { accessToken, refreshToken, expiresIn }
POST   /auth/logout             → 204
POST   /auth/totp/enable        → { qrCode, secret }
POST   /auth/totp/verify        → 204
GET    /users/me                → User
PATCH  /users/me                → User
GET    /.well-known/jwks.json   → JWKS (public key for JWT validation)
```

**DynamoDB Schema** (single-table design):
```
Table: identity-users
PK (UserId)      SK              Attributes
USER#<uuid>      PROFILE         email, username, passwordHash (bcrypt), kycStatus, twoFactorEnabled, createdAt
USER#<uuid>      TOTP            secret (encrypted with KMS), backupCodes
EMAIL#<email>    REF             userId  ← GSI for email lookup
```

**JWT Structure**:
```json
{
  "sub": "<userId>",
  "email": "user@example.com",
  "username": "trader1",
  "iat": 1234567890,
  "exp": 1234571490,
  "iss": "https://api.identity.cryptotrade.internal"
}
```
- Access token TTL: **1 hour**
- Refresh token TTL: **7 days**, stored in Redis with revocation support
- Algorithm: **RS256** (asymmetric — private key in Secrets Manager, public JWKS endpoint)

**Events Published**:
```
identity.v1.UserRegistered  → { userId, email, username, timestamp }
identity.v1.UserKYCApproved → { userId, kycStatus, timestamp }
```

---

### 3.2 MarketData Service

**AWS Stack**: ECS Fargate (ingestion), MSK Kafka (streaming), ElastiCache Redis (hot data), API Gateway WebSocket

**Architecture**:
```
External Exchange WebSocket APIs (Binance, OKX, etc.)
    ↓
Ingestion Fargate tasks (one per exchange)
    ↓ produce
MSK Kafka topics:
  market.tickers.{symbol}
  market.orderbook.{symbol}
  market.trades.{symbol}
    ↓ consume
Aggregator Fargate tasks
    ↓ write hot data
ElastiCache Redis (orderbook snapshots, last ticker)
    ↓
API Gateway WebSocket → broadcast to subscribed clients
```

**REST Endpoints** (unauthenticated):
```
GET /market/ticker/{symbol}            → Ticker
GET /market/orderbook/{symbol}?depth=  → OrderBook
GET /market/trades/{symbol}?limit=     → Trade[]
GET /market/symbols                    → string[]
GET /market/candles/{symbol}?interval=&limit= → Candle[]
```

**WebSocket Subscriptions**:
```
Connect: wss://ws.marketdata.../market/orderbook/BTC-USDT
Server sends: { type: "orderbook", data: OrderBook } on every book update

Connect: wss://ws.marketdata.../market/ticker/BTC-USDT
Server sends: { type: "ticker", data: Ticker } every 1s

Connect: wss://ws.marketdata.../market/trades/BTC-USDT
Server sends: { type: "trade", data: Trade } on every matched trade
```

**Redis Key Schema**:
```
orderbook:{symbol}     → JSON (OrderBook snapshot, TTL 5s)
ticker:{symbol}        → JSON (Ticker, TTL 2s)
trades:{symbol}        → List (last 100 trades, LPUSH + LTRIM)
```

---

### 3.3 SpotTrading Service

**AWS Stack**: EKS (order-engine Deployment), DynamoDB (orders), Aurora PostgreSQL (trade history, balance ledger), ElastiCache Redis (order book mirror, balance cache), SQS FIFO (order queue)

**API Contract**:
```
# Market Data (unauthenticated)
GET  /market/ticker/{symbol}             → Ticker (proxy to MarketData)
GET  /market/orderbook/{symbol}          → OrderBook (local cache)

# Orders (authenticated)
POST   /orders                           → Order
DELETE /orders/{orderId}                 → 204
GET    /orders/open?symbol=              → Order[]
GET    /orders/history?symbol=&limit=    → Order[]
GET    /orders/{orderId}                 → Order

# Account
GET    /account/portfolio               → Portfolio
```

**DynamoDB Schema** (orders):
```
Table: spot-orders-{env}
PK: orderId (UUID)         SK: userId
GSI1: userId + createdAt   (query open orders by user)
GSI2: symbol + status      (query open orders by market)

Attributes: symbol, type, side, status, price, quantity, filledQuantity,
            avgFillPrice, timeInForce, clientOrderId, createdAt, updatedAt
```

**Aurora PostgreSQL Schema** (trade history + ledger):
```sql
-- Trade history (immutable)
CREATE TABLE trades (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  symbol       VARCHAR(20) NOT NULL,
  maker_order_id UUID NOT NULL,
  taker_order_id UUID NOT NULL,
  price        NUMERIC(20, 8) NOT NULL,
  quantity     NUMERIC(20, 8) NOT NULL,
  maker_side   VARCHAR(4) NOT NULL,  -- 'buy' | 'sell'
  executed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Balance ledger (append-only, double-entry)
CREATE TABLE balance_entries (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID NOT NULL,
  asset        VARCHAR(10) NOT NULL,
  amount       NUMERIC(20, 8) NOT NULL,  -- positive=credit, negative=debit
  entry_type   VARCHAR(30) NOT NULL,     -- 'TRADE_BUY', 'TRADE_SELL', 'DEPOSIT', etc.
  reference_id UUID,                     -- orderId or depositId
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX ON balance_entries (user_id, asset);
```

**Order Matching Flow**:
```
POST /orders
  → Validate (balance check via Redis cache)
  → Write to DynamoDB (status: open)
  → Publish to SQS FIFO queue (deduplication by clientOrderId)
  → Order Engine pod consumes from SQS
  → Match against in-memory order book (sorted sets in Redis)
  → On fill: write trade to Aurora, update DynamoDB status
  → Publish order_update event to EventBridge
  → EventBridge rule → user WS connection (via API Gateway)
```

**Events Published**:
```
spot.v1.OrderPlaced   → { orderId, userId, symbol, side, type, price, quantity }
spot.v1.OrderFilled   → { orderId, tradeId, symbol, executedPrice, executedQty }
spot.v1.OrderCancelled → { orderId, userId, symbol }
spot.v1.TradeSummary  → daily aggregation for reporting
```

---

### 3.4 FuturesTrading Service

**AWS Stack**: EKS (position-engine, liquidation-engine), Aurora PostgreSQL (positions, orders, ledger), ElastiCache Redis (mark prices, position cache), SQS FIFO

**API Contract**:
```
# Account
GET  /account/info                       → FuturesAccountInfo
POST /account/leverage                   → 204   body: { symbol, leverage }
POST /account/margin-mode                → 204   body: { symbol, marginMode }

# Orders
POST   /orders                           → Order
DELETE /orders/{orderId}                 → 204
GET    /orders/open?symbol=              → Order[]

# Positions
GET    /positions                        → FuturesPosition[]
POST   /positions/{id}/close             → Order  (market close order)
POST   /positions/{id}/margin            → 204   body: { amount }
```

**Aurora PostgreSQL Schema**:
```sql
CREATE TABLE futures_positions (
  id                  UUID PRIMARY KEY,
  user_id             UUID NOT NULL,
  symbol              VARCHAR(20) NOT NULL,
  side                VARCHAR(5) NOT NULL,       -- 'long' | 'short'
  leverage            SMALLINT NOT NULL,
  margin_mode         VARCHAR(10) NOT NULL,       -- 'cross' | 'isolated'
  entry_price         NUMERIC(20, 8) NOT NULL,
  quantity            NUMERIC(20, 8) NOT NULL,
  margin              NUMERIC(20, 8) NOT NULL,
  realized_pnl        NUMERIC(20, 8) DEFAULT 0,
  status              VARCHAR(10) NOT NULL,       -- 'open' | 'closed' | 'liquidated'
  opened_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  closed_at           TIMESTAMPTZ
);
CREATE INDEX ON futures_positions (user_id, status);
CREATE INDEX ON futures_positions (symbol, status);  -- for liquidation scanner

CREATE TABLE futures_orders (
  -- same shape as spot orders, with additional columns:
  leverage            SMALLINT,
  margin_mode         VARCHAR(10),
  position_id         UUID REFERENCES futures_positions(id),
  reduce_only         BOOLEAN DEFAULT FALSE,
  position_side       VARCHAR(5)  -- 'long' | 'short'
);
```

**Liquidation Engine** (background EKS CronJob):
```
Every 100ms:
  1. Fetch all mark prices from Redis (pushed by MarketData)
  2. Query positions where status='open'
  3. Compute margin ratio = margin / (quantity * markPrice) for cross
     OR margin / notional for isolated
  4. If marginRatio < maintenanceMarginRate (0.5%):
     → Place market close order (SQS FIFO, priority=HIGH)
     → Update position status to 'liquidated'
     → Publish futures.v1.PositionLiquidated event
```

**Events Published**:
```
futures.v1.PositionOpened     → { positionId, userId, symbol, side, leverage, entryPrice }
futures.v1.PositionClosed     → { positionId, realizedPnl, closePrice }
futures.v1.PositionLiquidated → { positionId, userId, symbol, liqPrice, lossAmount }
futures.v1.FundingRateApplied → { symbol, fundingRate, timestamp }
```

---

### 3.5 Deposit Service

**AWS Stack**: ECS Fargate, Step Functions (workflow), Aurora PostgreSQL, SQS

**API Contract**:
```
GET  /deposit/networks/{asset}            → Network[]
GET  /deposit/address?asset=&network=     → DepositAddress
GET  /deposit/history?limit=              → DepositRecord[]
```

**Step Functions Workflow**:
```
DepositDetected (blockchain monitor)
  → CreateDepositRecord (status: pending)
  → WaitForConfirmations (polling every 30s)
  → [N < requiredConfirmations] → loop
  → [N >= requiredConfirmations]
  → CreditBalance (Aurora ledger entry in SpotTrading)
  → UpdateRecord (status: confirmed)
  → PublishEvent (finance.v1.DepositConfirmed)
  → SendNotification (via Notification service EventBridge)
```

**Aurora Schema**:
```sql
CREATE TABLE deposit_addresses (
  id         UUID PRIMARY KEY,
  user_id    UUID NOT NULL,
  asset      VARCHAR(10) NOT NULL,
  network    VARCHAR(20) NOT NULL,
  address    VARCHAR(200) NOT NULL UNIQUE,
  tag        VARCHAR(64),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE deposit_records (
  id                      UUID PRIMARY KEY,
  user_id                 UUID NOT NULL,
  asset                   VARCHAR(10) NOT NULL,
  network                 VARCHAR(20) NOT NULL,
  amount                  NUMERIC(20, 8) NOT NULL,
  status                  VARCHAR(15) NOT NULL,
  tx_hash                 VARCHAR(100),
  confirmations           INTEGER DEFAULT 0,
  required_confirmations  INTEGER NOT NULL,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  completed_at            TIMESTAMPTZ
);
```

**Events Published**:
```
finance.v1.DepositConfirmed  → { userId, asset, amount, network, txHash }
```

---

### 3.6 Withdrawal Service

**AWS Stack**: ECS Fargate, Step Functions (approval workflow), Aurora PostgreSQL, AWS KMS

**API Contract**:
```
POST /withdrawal                           → WithdrawalRecord
GET  /withdrawal/history?limit=            → WithdrawalRecord[]
POST /withdrawal/{id}/cancel               → 204
GET  /withdrawal/fee?asset=&network=       → { fee, minWithdrawal }
```

**Step Functions Workflow** (human approval gate):
```
WithdrawalRequested
  → ValidateBalance (check SpotTrading ledger)
  → AMLCheck (RiskCompliance service synchronous call)
  → [AML: blocked] → Reject → PublishEvent(WithdrawalRejected)
  → LockFunds (debit from available balance)
  → EmailConfirmation (user must click link, 24h TTL)
  → WaitForApproval (Step Functions .waitForTaskToken, up to 24h)
  → [Timeout] → UnlockFunds → Cancel
  → [Approved]
  → BroadcastToBlockchain (via custody provider API)
  → WaitForTxConfirmation (polling)
  → UpdateRecord (status: completed)
  → PublishEvent (finance.v1.WithdrawalCompleted)
```

---

### 3.7 RiskCompliance Service

**AWS Stack**: ECS Fargate, Aurora PostgreSQL, EventBridge (consumes all domain events)

**Responsibilities**:
- AML screening on withdrawals (synchronous API)
- Position limit enforcement (max notional per user)
- Trade surveillance (wash trading, spoofing detection)
- Audit log aggregation

**EventBridge Subscriptions** (receives from all domains):
```
spot.v1.OrderFilled        → log trade, check wash trading
spot.v1.TradeSummary       → daily trade volume report
futures.v1.PositionOpened  → check position limits
futures.v1.PositionLiquidated → log liquidation event
finance.v1.WithdrawalCompleted → AML post-transaction monitor
identity.v1.UserRegistered → trigger KYC flow
```

**AML API** (called synchronously by Withdrawal service):
```
POST /aml/check
Body: { userId, asset, amount, destinationAddress }
Response: { decision: "approve" | "block" | "review", reason?: string }
SLA: < 500ms
```

---

### 3.8 Notification Service

**AWS Stack**: Lambda (consumer), DynamoDB (templates, logs), SNS + SES + FCM (delivery)

**EventBridge Subscriptions**:
```
spot.v1.OrderFilled        → "Your {side} order for {qty} {asset} was filled at {price}"
futures.v1.PositionLiquidated → "URGENT: Your {symbol} position was liquidated"
finance.v1.DepositConfirmed  → "{amount} {asset} deposited successfully"
finance.v1.WithdrawalCompleted → "Withdrawal of {amount} {asset} completed"
identity.v1.UserKYCApproved  → "Your KYC verification was approved"
```

**Lambda handler pattern**:
```
EventBridge rule → SQS → Lambda (retry 3x, DLQ)
  → Lookup user notification preferences (DynamoDB)
  → Render template with event data
  → Route by preference: SES (email) | SNS (push) | both
  → Log delivery result (DynamoDB)
```

---

## 4. Infrastructure Design (Terraform)

### 4.1 Module Interfaces

#### `modules/account-factory/variables.tf`
```hcl
variable "domain"                { type = string }  # "spottrading"
variable "department"            { type = string }  # "Trading"
variable "environment"           { type = string }  # "prod"
variable "aws_account_id"        { type = string }  # target account ID
variable "vpc_cidr"              { type = string }  # "10.2.0.0/16"
variable "cost_center"           { type = string }  # "CC-TRD-SPOT"
variable "tgw_id"                { type = string }  # from network account
variable "log_archive_bucket"    { type = string }  # from log-archive account
variable "cross_account_event_targets" {
  type    = map(string)  # { riskcompliance = "111122223333" }
  default = {}
}
variable "owner_email"           { type = string }
variable "region"                { type = string; default = "ap-northeast-2" }
```

#### `modules/account-factory` Outputs
```hcl
output "vpc_id"                  { value = module.vpc.vpc_id }
output "private_subnet_ids"      { value = module.vpc.private_subnet_ids }
output "public_subnet_ids"       { value = module.vpc.public_subnet_ids }
output "db_subnet_ids"           { value = module.vpc.db_subnet_ids }
output "firewall_subnet_ids"     { value = module.vpc.firewall_subnet_ids }
output "eventbridge_bus_arn"     { value = aws_cloudwatch_event_bus.domain.arn }
output "eventbridge_bus_name"    { value = aws_cloudwatch_event_bus.domain.name }
output "guardduty_detector_id"   { value = aws_guardduty_detector.this.id }
output "common_tags"             { value = local.common_tags }
```

#### `modules/domain-vpc/variables.tf`
```hcl
variable "name"    { type = string }
variable "cidr"    { type = string }   # "10.2.0.0/16"
variable "tgw_id"  { type = string }
variable "azs"     { type = list(string); default = ["ap-northeast-2a", "ap-northeast-2b", "ap-northeast-2c"] }
variable "tags"    { type = map(string) }
```

**Subnet layout** (per AZ, 3 AZs):
```
10.2.0.0/16 → VPC

Public subnets    (ALB, NAT): /24 each (3×)  → 10.2.0.0, 10.2.1.0, 10.2.2.0
Firewall subnets  (NFW):      /28 each (3×)  → 10.2.3.0/28, 10.2.3.16/28, 10.2.3.32/28
Private subnets   (EKS/ECS):  /22 each (3×)  → 10.2.8.0, 10.2.12.0, 10.2.16.0
DB subnets        (RDS):      /24 each (3×)  → 10.2.20.0, 10.2.21.0, 10.2.22.0
```

#### `modules/eks-cluster/variables.tf`
```hcl
variable "cluster_name"  { type = string }
variable "k8s_version"   { type = string; default = "1.31" }
variable "vpc_id"         { type = string }
variable "subnet_ids"     { type = list(string) }  # private subnets
variable "node_groups"    {
  type = map(object({
    instance_type = string
    min_size      = number
    max_size      = number
    disk_size_gb  = optional(number, 50)
  }))
}
variable "tags"           { type = map(string) }
```

#### `modules/aurora-cluster/variables.tf`
```hcl
variable "cluster_id"      { type = string }
variable "engine_version"  { type = string; default = "16.3" }
variable "instance_class"  { type = string; default = "db.r6g.large" }
variable "instance_count"  { type = number; default = 2 }
variable "database_name"   { type = string }
variable "subnet_ids"      { type = list(string) }   # db subnets
variable "vpc_id"          { type = string }
variable "allowed_sg_ids"  { type = list(string) }   # EKS node SGs
variable "tags"            { type = map(string) }
```

### 4.2 Account Consumer Example

```hcl
# accounts/prod/spottrading/main.tf

terraform {
  backend "s3" {
    bucket         = "tf-state-trading-platform-SPOT_ACCOUNT_ID"
    key            = "prod/spottrading/terraform.tfstate"
    region         = "ap-northeast-2"
    dynamodb_table = "tf-state-locks"
    encrypt        = true
    kms_key_id     = "alias/terraform-state-key"
  }
}

data "terraform_remote_state" "network" {
  backend = "s3"
  config  = {
    bucket = "tf-state-trading-platform-NETWORK_ACCOUNT_ID"
    key    = "prod/network/terraform.tfstate"
    region = "ap-northeast-2"
  }
}

module "account_baseline" {
  source = "../../../modules/account-factory"

  domain      = "SpotTrading"
  department  = "Trading"
  environment = "prod"
  vpc_cidr    = "10.2.0.0/16"
  cost_center = "CC-TRD-SPOT"
  tgw_id      = data.terraform_remote_state.network.outputs.tgw_prod_id
  log_archive_bucket = "trading-platform-logs-LOGARCHIVE_ACCOUNT_ID"
  owner_email = "trading-team@company.com"
  cross_account_event_targets = {
    riskcompliance = "111122223333"
    notification   = "444455556666"
  }
}

module "eks" {
  source = "../../../modules/eks-cluster"

  cluster_name = "spot-trading-prod"
  vpc_id       = module.account_baseline.vpc_id
  subnet_ids   = module.account_baseline.private_subnet_ids
  node_groups  = {
    order_engine = {
      instance_type = "c6i.2xlarge"
      min_size      = 3
      max_size      = 20
    }
    api = {
      instance_type = "t3.large"
      min_size      = 2
      max_size      = 10
    }
  }
  tags = module.account_baseline.common_tags
}

module "dynamodb_orders" {
  source       = "../../../modules/dynamodb-table"
  table_name   = "spot-orders-prod"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "orderId"
  range_key    = "userId"
  global_secondary_indexes = [
    { name = "UserCreatedAt", hash_key = "userId",  range_key = "createdAt" },
    { name = "SymbolStatus",  hash_key = "symbol",  range_key = "status"    }
  ]
  tags = module.account_baseline.common_tags
}

module "aurora" {
  source        = "../../../modules/aurora-cluster"
  cluster_id    = "spot-trading-prod"
  database_name = "spottrading"
  instance_class = "db.r6g.large"
  instance_count = 2
  subnet_ids    = module.account_baseline.db_subnet_ids
  vpc_id        = module.account_baseline.vpc_id
  allowed_sg_ids = [module.eks.node_security_group_id]
  tags          = module.account_baseline.common_tags
}

module "redis" {
  source         = "../../../modules/elasticache-redis"
  cluster_id     = "spot-trading-prod"
  node_type      = "cache.r6g.large"
  num_shards     = 2
  replicas_per_shard = 1
  subnet_ids     = module.account_baseline.db_subnet_ids
  vpc_id         = module.account_baseline.vpc_id
  allowed_sg_ids = [module.eks.node_security_group_id]
  tags           = module.account_baseline.common_tags
}
```

### 4.3 Network Account Design

```hcl
# accounts/prod/network/main.tf

# Transit Gateway (Prod) — all prod domain VPCs attach here
resource "aws_ec2_transit_gateway" "prod" {
  description                     = "Production TGW"
  auto_accept_shared_attachments  = "enable"
  default_route_table_association = "disable"
  default_route_table_propagation = "disable"
  tags = { Name = "tgw-prod", Environment = "prod" }
}

# TGW Route Tables
resource "aws_ec2_transit_gateway_route_table" "prod_domains" {
  transit_gateway_id = aws_ec2_transit_gateway.prod.id
  tags = { Name = "tgw-rt-prod-domains" }
}

resource "aws_ec2_transit_gateway_route_table" "prod_egress" {
  transit_gateway_id = aws_ec2_transit_gateway.prod.id
  tags = { Name = "tgw-rt-prod-egress" }
}

# Centralized egress VPC with Network Firewall
module "egress_vpc" {
  source = "../../../modules/egress-vpc"
  cidr   = "10.255.0.0/24"
  tgw_id = aws_ec2_transit_gateway.prod.id

  firewall_rules = {
    stateful_rules = [
      # Allow HTTPS to approved external APIs only
      "pass tcp any any -> $EXTERNAL_CRYPTO_APIS 443",
      # Block all other outbound
      "drop tcp any any -> any 443",
      "drop udp any any -> any any"
    ]
  }
}
```

### 4.4 Terraform State Organization

```
S3 State Buckets (one per account):
  tf-state-trading-platform-{account-id}
  ├── prod/network/terraform.tfstate
  ├── prod/security/terraform.tfstate
  ├── prod/spottrading/terraform.tfstate
  ├── prod/futurestrading/terraform.tfstate
  ├── prod/deposit/terraform.tfstate
  ...

State dependencies (read via terraform_remote_state):
  spottrading → network (TGW ID)
  spottrading → log-archive (S3 bucket)
  futurestrading → network (TGW ID)
  all domain accounts → network, log-archive, security
```

---

## 5. EventBridge Schema Contracts

### 5.1 Schema Registry Location

```
AWS EventBridge Schema Registry: trading-platform-prod
  → trading.spot.v1.OrderFilled
  → trading.spot.v1.OrderPlaced
  → trading.futures.v1.PositionOpened
  → trading.futures.v1.PositionLiquidated
  → finance.deposit.v1.DepositConfirmed
  → finance.withdrawal.v1.WithdrawalCompleted
  → identity.v1.UserRegistered
  → identity.v1.UserKYCApproved
```

### 5.2 Canonical Event Envelope

```json
{
  "version": "0",
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "source": "trading.spot",
  "detail-type": "OrderFilled",
  "time": "2026-03-08T12:00:00Z",
  "account": "111122223333",
  "region": "ap-northeast-2",
  "detail": {
    "schemaVersion": "v1",
    "orderId": "...",
    "userId": "...",
    "symbol": "BTC-USDT",
    "side": "buy",
    "executedPrice": "43250.00",
    "executedQty": "0.5",
    "tradeId": "...",
    "timestamp": 1709895600000
  }
}
```

### 5.3 Cross-Account Rules

```hcl
# In spottrading-prod account
resource "aws_cloudwatch_event_rule" "to_riskcompliance" {
  name           = "spot-to-riskcompliance-order-filled"
  event_bus_name = aws_cloudwatch_event_bus.domain.name
  event_pattern  = jsonencode({
    source      = ["trading.spot"]
    detail-type = ["OrderFilled"]
  })
}

resource "aws_cloudwatch_event_target" "riskcompliance_bus" {
  rule           = aws_cloudwatch_event_rule.to_riskcompliance.name
  event_bus_name = aws_cloudwatch_event_bus.domain.name
  arn            = "arn:aws:events:ap-northeast-2:RISKCOMPLIANCE_ACCOUNT:event-bus/riskcompliance.prod"
  role_arn       = aws_iam_role.eventbridge_cross_account.arn
}
```

---

## 6. Kubernetes Deployment Design

### 6.1 EKS Structure per Domain

```
Namespace: spottrading-prod
├── Deployment: spot-api            (2-10 replicas, HPA on CPU/RPS)
├── Deployment: order-engine        (3 replicas fixed, anti-affinity spread)
├── StatefulSet: -                  (no stateful workloads in K8s — DB is Aurora)
├── Service: spot-api-svc           (ClusterIP → ALB Ingress)
├── Ingress: spot-api-ingress       (ALB Controller, TLS via ACM)
├── HorizontalPodAutoscaler
│   ├── spot-api: CPU 70%, min=2, max=10
│   └── order-engine: disabled (fixed 3 for HA)
├── PodDisruptionBudget
│   └── order-engine: minAvailable=2
└── ConfigMap: spot-config          (non-secret config)

Secrets (from AWS Secrets Manager via External Secrets Operator):
  ├── aurora-credentials
  ├── redis-auth-token
  └── sqs-credentials
```

### 6.2 Spot API Deployment

```yaml
# k8s/base/spot-trading/deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: spot-api
  namespace: spottrading-prod
spec:
  replicas: 3
  selector:
    matchLabels: { app: spot-api }
  template:
    metadata:
      labels: { app: spot-api, version: "1.0" }
    spec:
      serviceAccountName: spot-api-sa
      containers:
        - name: spot-api
          image: ${ECR_REGISTRY}/spot-api:${IMAGE_TAG}
          ports:
            - containerPort: 8000
          env:
            - name: AURORA_HOST
              valueFrom: { secretKeyRef: { name: aurora-credentials, key: host } }
            - name: REDIS_URL
              valueFrom: { secretKeyRef: { name: redis-auth-token, key: url } }
            - name: EVENTBRIDGE_BUS
              value: "spottrading.prod"
          resources:
            requests: { cpu: "200m", memory: "512Mi" }
            limits:   { cpu: "1000m", memory: "1Gi" }
          livenessProbe:
            httpGet: { path: /health, port: 8000 }
            initialDelaySeconds: 10
            periodSeconds: 10
          readinessProbe:
            httpGet: { path: /ready, port: 8000 }
            initialDelaySeconds: 5
            periodSeconds: 5
      topologySpreadConstraints:
        - maxSkew: 1
          topologyKey: topology.kubernetes.io/zone
          whenUnsatisfiable: DoNotSchedule
```

### 6.3 GitOps (ArgoCD)

```
ArgoCD (in shared-services account, cross-account deploy):

Application: spot-trading-prod
  Source: github.com/org/trading-platform-iac
  Path:   k8s/overlays/prod/spottrading/
  Dest:   spottrading-prod EKS cluster
  Sync:   Manual (production), Automated (staging)

Kustomize overlay structure:
k8s/
├── base/
│   ├── spot-trading/
│   │   ├── deployment.yaml
│   │   ├── service.yaml
│   │   ├── hpa.yaml
│   │   └── kustomization.yaml
│   └── futures-trading/
└── overlays/
    ├── staging/
    │   └── spottrading/
    │       └── kustomization.yaml  # patches: replicas=1, smaller resources
    └── prod/
        └── spottrading/
            └── kustomization.yaml  # patches: image tag, prod resource limits
```

---

## 7. Security Design

### 7.1 Authentication Flow

```
1. User → POST /auth/login (identity-prod)
2. identity-prod validates password (bcrypt)
3. identity-prod issues RS256 JWT (access 1h) + refresh token (Redis, 7d)
4. Browser stores tokens in memory (authStore, NOT localStorage for access token)
   ↑ refresh token only in httpOnly cookie via Set-Cookie header
5. API request → Authorization: Bearer <accessToken>
6. Service API Gateway Authorizer Lambda:
   a. Verify JWT signature against JWKS endpoint (cached 5min)
   b. Verify exp, iss
   c. Return IAM policy (allow/deny) + userId context
7. Access token expires → browser calls POST /auth/refresh with cookie
8. identity-prod rotates refresh token (token rotation), issues new access token
```

### 7.2 API Gateway Authorizer

```python
# Lambda authorizer (shared across all service API Gateways)
import jwt
import requests
from functools import lru_cache

IDENTITY_JWKS_URL = "https://api.identity.cryptotrade.internal/.well-known/jwks.json"

@lru_cache(maxsize=1, typed=False)
def get_public_keys():
    """Cache JWKS for 5 minutes to avoid hammering identity service"""
    return requests.get(IDENTITY_JWKS_URL, timeout=2).json()

def handler(event, context):
    token = event["authorizationToken"].replace("Bearer ", "")
    try:
        payload = jwt.decode(token, get_public_keys(), algorithms=["RS256"],
                             options={"verify_exp": True})
        return generate_policy(payload["sub"], "Allow", event["methodArn"])
    except jwt.ExpiredSignatureError:
        raise Exception("Unauthorized")  # API GW returns 401
    except Exception:
        raise Exception("Unauthorized")

def generate_policy(user_id, effect, resource):
    return {
        "principalId": user_id,
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [{"Action": "execute-api:Invoke", "Effect": effect, "Resource": resource}]
        },
        "context": {"userId": user_id}
    }
```

### 7.3 Network Security Layers

```
Layer 1: AWS WAF (on ALB)
  Rules: CommonRuleSet, IP reputation, SQLi, KnownBadInputs, RateLimit (2000/5min/IP)

Layer 2: AWS Network Firewall (centralized egress)
  Stateful rules: domain allowlist for outbound (exchange APIs, custody providers)
  Stateless rules: block inbound on non-443/non-80 ports

Layer 3: Security Groups
  ALB SG: inbound 443 from 0.0.0.0/0
  EKS node SG: inbound 8000 from ALB SG only
  Aurora SG: inbound 5432 from EKS node SG only
  Redis SG: inbound 6379 from EKS node SG only

Layer 4: IAM (least privilege)
  spot-api-sa (K8s ServiceAccount → IRSA):
    - sqs:SendMessage, sqs:ReceiveMessage on spot-orders-queue
    - dynamodb:PutItem, GetItem, UpdateItem, Query on spot-orders table
    - events:PutEvents on spottrading EventBridge bus
    - NO cross-account access
```

---

## 8. CI/CD Pipeline Design

### 8.1 Application CI (trading-platform-services repo)

```yaml
# .github/workflows/ci.yml
on:
  push:
    branches: [main, develop]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
      - run: pnpm install --frozen-lockfile
      - run: pnpm type-check
      - run: pnpm lint
      - run: pnpm test

  build-and-push:
    if: github.ref == 'refs/heads/main'
    needs: test
    strategy:
      matrix:
        service: [spot-trading, futures-trading, deposit, withdrawal, identity, market-data]
    steps:
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: arn:aws:iam::SHARED_SERVICES_ACCOUNT:role/github-actions-ecr-push
      - run: |
          docker build -t $ECR_REGISTRY/${{ matrix.service }}:$GITHUB_SHA services/${{ matrix.service }}/
          docker push $ECR_REGISTRY/${{ matrix.service }}:$GITHUB_SHA
      - run: |
          # Update ArgoCD image tag (kustomize edit set image)
          cd k8s/overlays/staging/${{ matrix.service }}
          kustomize edit set image $ECR_REGISTRY/${{ matrix.service }}:$GITHUB_SHA
          git commit -am "ci: update ${{ matrix.service }} to $GITHUB_SHA"
          git push  # triggers ArgoCD auto-sync on staging
```

### 8.2 IaC CI (trading-platform-iac repo)

```yaml
# .github/workflows/terraform.yml
on:
  pull_request:
    paths: ['accounts/**', 'modules/**']

jobs:
  plan:
    strategy:
      matrix:
        account: [network, spottrading, futurestrading, deposit, identity, marketdata]
        env: [prod, dev]
    steps:
      - run: terraform init
        working-directory: accounts/${{ matrix.env }}/${{ matrix.account }}
      - run: terraform plan -out=tfplan
        working-directory: accounts/${{ matrix.env }}/${{ matrix.account }}
      - uses: actions/upload-artifact@v4
        with:
          name: tfplan-${{ matrix.env }}-${{ matrix.account }}
          path: accounts/${{ matrix.env }}/${{ matrix.account }}/tfplan

  apply:
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    needs: plan
    environment: terraform-apply  # requires manual approval in GitHub
    steps:
      - run: terraform apply tfplan
```

---

## 9. Frontend Environment Variables Mapping

| Variable | Resolves To | Domain Account |
|----------|-------------|----------------|
| `NEXT_PUBLIC_IDENTITY_API_URL` | ALB DNS in identity-prod | identity-prod |
| `NEXT_PUBLIC_SPOT_API_URL` | ALB DNS in spottrading-prod | spottrading-prod |
| `NEXT_PUBLIC_FUTURES_API_URL` | ALB DNS in futurestrading-prod | futurestrading-prod |
| `NEXT_PUBLIC_FINANCE_API_URL` | ALB DNS in deposit-prod | deposit-prod |
| `NEXT_PUBLIC_WS_URL` | API GW WebSocket in marketdata-prod | marketdata-prod |

All DNS names follow pattern: `api.{domain}.cryptotrade.internal` via Route53 private hosted zone in network-prod account, resolved through VPC → TGW → domain VPC.

---

## 10. Implementation Order

Based on dependencies, implement in this sequence:

| Step | Work | Dependency |
|------|------|------------|
| 1 | AWS Organizations + SCPs + Tag Policies | — |
| 2 | Log-archive account (S3 buckets) | Step 1 |
| 3 | Security account (GuardDuty delegated admin) | Step 1 |
| 4 | Network account (TGW prod/dev, egress VPC, Network Firewall) | Step 2, 3 |
| 5 | `account-factory` Terraform module | Step 4 |
| 6 | Identity service account (simplest domain, no external events) | Step 5 |
| 7 | MarketData service account + Kafka + WebSocket API GW | Step 5 |
| 8 | Frontend `apps/web` pointing to identity + marketdata | Step 6, 7 |
| 9 | SpotTrading service + EKS + DynamoDB + Aurora | Step 5, 6 |
| 10 | FuturesTrading service + position engine | Step 5, 6 |
| 11 | Deposit + Withdrawal services + Step Functions | Step 5, 6 |
| 12 | Notification + RiskCompliance services | Step 6–11 |
| 13 | EventBridge cross-account wiring (all rules) | Step 6–12 |
| 14 | ArgoCD GitOps setup | Step 9–12 |
| 15 | End-to-end integration testing | All |
