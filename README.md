# Trading Platform

Enterprise-grade cryptocurrency and fiat trading platform built with a microservices architecture on AWS.

---

## What Was Built

A full-stack trading platform across **6 independently deployable services**, a **Next.js frontend**, and a **multi-account AWS infrastructure** managed entirely with Terraform.

All 6 features completed via PDCA methodology with gap analysis match rates of 90%+.

| Service | Match Rate | Description |
|---|:---:|---|
| identity-service | 99.3% | JWT auth, TOTP 2FA, user management |
| deposit-service | 99.0% | Crypto/fiat deposit lifecycle |
| spot-trading-service | 95.5% | Order book, positions, real-time trades |
| withdrawal-service | 95.5% | Crypto/fiat withdrawal with AML checks |
| market-data-service | 90.5% | Kafka ingestion, candlestick, WebSocket |
| trading-platform | 90.6% | Frontend shell, routing, shared layout |

---

## Architecture

### System Overview

```
                        ┌─────────────────────────────┐
                        │     CloudFront + WAF (L7)    │
                        └──────────────┬──────────────┘
                                       │
                        ┌──────────────▼──────────────┐
                        │     API Gateway (HTTP/WS)    │
                        │   Lambda Authorizer (JWT)    │
                        └──────────────┬──────────────┘
                                       │ Transit Gateway
              ┌──────────────┬─────────▼──────┬──────────────┐
              │              │                │              │
     ┌────────▼───┐  ┌───────▼────┐  ┌───────▼────┐  ┌──────▼─────┐
     │  Identity  │  │    Spot    │  │   Market   │  │  Finance   │
     │  Service   │  │  Trading   │  │    Data    │  │ (Deposit / │
     │ (FastAPI)  │  │ (FastAPI)  │  │ (FastAPI)  │  │ Withdraw)  │
     └────────────┘  └───────────┘  └────────────┘  └────────────┘
          │               │               │               │
        Aurora          Aurora          MSK Kafka        Aurora
       PostgreSQL      PostgreSQL        + Redis         PostgreSQL
                        + Redis       + DynamoDB       Step Functions
                       + DynamoDB                      + EventBridge
```

### AWS Multi-Account Structure

```
AWS Organizations
├── Production OU
│   ├── identity-account
│   ├── spot-trading-account
│   ├── market-data-account
│   ├── deposit-account
│   └── withdrawal-account
├── Development OU        (mirrors Production)
├── Security OU           (GuardDuty master, centralized logs)
└── Infrastructure OU     (Transit Gateway, Network Firewall)
```

Each account is provisioned via the `account-factory` Terraform module, which automatically sets up:
- VPC with public/private subnets and NAT Gateway
- CloudTrail (multi-region, forwarded to log-archive)
- GuardDuty (S3 + EKS audit + EBS malware protection)
- KMS Customer Managed Key (rotation enabled)
- EventBridge domain bus
- Transit Gateway attachment
- SSM Parameter Store exports

---

## Services

### Identity Service
- Email signup / login with bcrypt password hashing
- JWT access tokens (15 min) + refresh tokens (7 days)
- TOTP-based 2FA (enable / verify)
- API Gateway HTTP API with Lambda JWT Authorizer (5 min TTL cache)

### Spot Trading Service
- Order placement (MARKET / LIMIT), cancellation
- Position tracking per user per asset
- Real-time order book via WebSocket API Gateway + Redis Pub/Sub
- Trade matching engine with Aurora PostgreSQL
- Internal `/positions/deduct` and `/positions/credit` endpoints for finance services

### Market Data Service
- MSK Kafka ingestion pipeline (3 brokers, KRaft mode, TLS + IAM)
- OHLCV candlestick builder via Lambda (MSK event source, batch 100)
- Candles stored in DynamoDB (PITR enabled, KMS encrypted)
- WebSocket streaming to frontend clients

### Deposit Service
- Crypto deposit: wallet address generation, blockchain confirmation tracking
- Fiat deposit: bank reference generation
- 7-state Step Functions workflow (PENDING → CONFIRMING → CONFIRMED → CREDITED)
- EventBridge event publishing on CREDITED
- HMAC-SHA256 webhook validation for external confirmations

### Withdrawal Service
- Crypto withdrawal: address validation, amount limits (ETH ≤10, BTC ≤1, USDT ≤50k)
- Fiat withdrawal: bank account + routing number
- AML daily limit check ($50,000 USD equivalent across all assets)
- Balance reservation pattern (deduct → execute, credit-back on failure)
- 7-state Step Functions workflow with retry/catch
- Cancel support for PENDING withdrawals only

### Market Data (Frontend)
- Next.js 14 App Router, TypeScript, Tailwind CSS
- Real-time price charts and order book display
- Deposit and withdrawal forms with status polling (10s interval)
- Zustand auth store, TanStack Query for server state

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js 14, TypeScript, Tailwind CSS, Zustand, TanStack Query |
| Backend | Python 3.12, FastAPI, asyncpg (raw SQL, no ORM) |
| Database | Aurora PostgreSQL 16.2 (writer + reader, db.r6g.large) |
| Cache | ElastiCache Redis (cache.r7g.medium, TLS) |
| Message Queue | MSK Kafka (KRaft mode, 3 brokers) |
| Workflow | AWS Step Functions (ASL state machines) |
| Events | EventBridge (cross-account routing) |
| Realtime | WebSocket API Gateway + Redis Pub/Sub |
| NoSQL | DynamoDB (candles, WebSocket connections) |
| Infrastructure | Terraform (HCL), AWS ECS Fargate |
| Monorepo | Turborepo + pnpm workspaces |

---

## Security

Defense-in-depth across 6 layers:

| Layer | Controls |
|---|---|
| **Perimeter** | CloudFront + WAF (SQLi, XSS, rate limit 2000/5min) |
| **Network** | AWS Network Firewall — Suricata rules: block TOR, crypto miners; egress domain allowlist |
| **Account** | SCPs: DenyRoot, DenyLeaveOrg, RequireApprovedRegions (ap-northeast-2), no prod↔dev peering |
| **Detection** | GuardDuty per account, CloudTrail multi-region, centralized log-archive (90-day) |
| **Encryption** | KMS CMK per account — RDS, S3, DynamoDB, EBS all encrypted at rest |
| **Auth** | JWT Lambda Authorizer, X-Internal-Token for service-to-service, HMAC-SHA256 webhooks |

---

## Tag Policy

Enforced at AWS Organizations level on ECS, Lambda, RDS, DynamoDB, and more:

| Tag | Example | Purpose |
|---|---|---|
| `Company` | `TradingCo` | Cost consolidation |
| `Environment` | `prod` / `dev` | Environment separation |
| `Domain` | `finance` / `identity` | Domain chargeback |
| `CostCenter` | `CC-001` | Financial reporting |
| `Team` | `platform` | Team accountability |
| `ManagedBy` | `terraform` | Drift detection |

---

## Project Structure

```
trading-app/
├── apps/
│   └── web/                    # Next.js frontend
│       └── src/
│           ├── app/            # App Router pages
│           ├── hooks/          # useDeposit, useWithdrawal (polling)
│           ├── services/       # financeApi, marketApi
│           └── stores/         # Zustand (auth)
│
├── services/
│   ├── identity/               # Auth & user management
│   ├── spot-trading/           # Orders, positions, trades
│   ├── market-data/            # Kafka → candles → WebSocket
│   ├── deposit/                # Deposit lifecycle
│   ├── withdrawal/             # Withdrawal + AML
│   └── shared/                 # Common utilities
│
├── packages/
│   └── types/                  # Shared TypeScript types
│
├── infra/
│   ├── org/                    # AWS Organizations, SCPs, Tag Policies
│   ├── modules/
│   │   ├── account-factory/    # Per-account baseline (VPC, CloudTrail, GuardDuty, KMS)
│   │   ├── network/            # Transit Gateway, Inspection VPC, Network Firewall
│   │   ├── ecs/                # ECS Fargate task/service module
│   │   ├── rds/                # Aurora PostgreSQL module
│   │   ├── redis/              # ElastiCache Redis module
│   │   ├── msk/                # Managed Kafka module
│   │   └── security/           # GuardDuty, CloudTrail, KMS helpers
│   └── environments/
│       ├── prod/               # Production Terraform root modules
│       └── dev/                # Development Terraform root modules
│
└── docs/
    └── archive/2026-03/        # PDCA documents for all 6 features
```

---

## Design Principles

**Domain-Driven Design** — Each service is a bounded context with its own domain model, repository interface (ABC), and PostgreSQL schema. Business logic never touches SQL directly.

**Clean Architecture (4-layer)** — `API Router → Application Service → Domain Model → Repository`. Dependency flows inward; infrastructure adapts to domain interfaces.

**Account-per-Domain** — AWS accounts are the strongest isolation boundary. A compromise in one service cannot affect another's IAM namespace, KMS keys, or VPC.

**Infrastructure as Code** — Every resource is declared in Terraform. The `account-factory` module ensures every account gets the same security baseline by construction, not convention.

**Balance Reservation** — Withdrawals deduct balance before execution; credit it back on failure or rejection. Idempotency enforced via Step Functions execution name = entity ID.

---

## Getting Started

### Prerequisites

- Node.js 20+ with pnpm
- Python 3.12+
- Docker + Docker Compose
- AWS CLI (configured for ap-northeast-2)
- Terraform 1.7+

### Local Development

```bash
# Install frontend dependencies
pnpm install

# Start all services (requires Docker)
docker compose up -d

# Run frontend dev server
pnpm dev

# Run backend service (example: identity)
cd services/identity
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

### Infrastructure

```bash
# Deploy to dev environment
cd infra/environments/dev
terraform init
terraform plan
terraform apply
```

---

## License

Private — all rights reserved.
