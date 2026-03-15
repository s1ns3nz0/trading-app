# AWS 멀티 어카운트 워크로드 설계서

## 암호화폐 거래 플랫폼 — "TradingPlatform"

> 본 문서는 `trading-app` 모노레포의 실제 코드(`infra/`, `services/`, `apps/`)를 분석하여 작성되었다.
> 모든 Terraform 코드와 설명에 실제 소스 파일 경로를 명시한다.

---

## 목차

1. [소프트웨어 개요](#1-소프트웨어-개요)
2. [도메인 분리 및 워크로드 설계](#2-도메인-분리-및-워크로드-설계)
3. [멀티 어카운트 아키텍처](#3-멀티-어카운트-아키텍처)
4. [인프라 네트워크 설계 (4-Tier)](#4-인프라-네트워크-설계-4-tier)
5. [EventBridge 크로스 어카운트 이벤트 설계](#5-eventbridge-크로스-어카운트-이벤트-설계)
6. [워크로드(스택)별 구현](#6-워크로드스택별-구현)
7. [Tag Policy](#7-tag-policy)
8. [비용 가시화 (Cost Visibility)](#8-비용-가시화-cost-visibility)
9. [리소스 가시화 (Resource Visibility)](#9-리소스-가시화-resource-visibility)

---

## 1. 소프트웨어 개요

### 1.1 서비스 설명

**TradingPlatform**은 암호화폐 현물 거래 플랫폼이다. 사용자 인증, 실시간 시세 스트리밍, 현물 주문/체결, 암호화폐 입출금을 제공한다.

- **프론트엔드**: Next.js 15 (App Router, React 19, Tailwind CSS v4, Zustand, React Query) — Vercel 배포
- **백엔드**: 5개 독립 마이크로서비스 + 공유 인프라 — AWS 멀티 어카운트 배포
- **모노레포**: Turborepo + pnpm 9.15.0 workspace, Node ≥20
- **공유 타입**: `packages/types/` — TypeScript 도메인 타입 (Order, Trade, Ticker, Portfolio 등)

### 1.2 서비스 전체 목록

| # | 서비스 | 위치 | 언어 | 컴퓨팅 | 핵심 기능 |
|---|--------|------|------|--------|----------|
| 1 | **Identity** | `services/identity/` | Python 3.12 (FastAPI) | Lambda | 회원가입, 로그인, JWT, TOTP 2FA, 이메일 인증 |
| 2 | **SpotTrading** | `services/spot-trading/` | Python 3.12 (FastAPI) | EKS | 주문 매칭, 호가창, 잔고 관리, 체결 |
| 3 | **MarketData** | `services/market-data/` | Python 3.12 | ECS Fargate + Lambda | 시세 수집, 캔들 생성, 실시간 스트리밍 |
| 4 | **Deposit** | `services/deposit/` | Python 3.12 (FastAPI) | ECS Fargate | 암호화폐 입금 확인, 잔고 반영 |
| 5 | **Withdrawal** | `services/withdrawal/` | Python 3.12 (FastAPI) | ECS Fargate | 출금 처리, AML 검증 |
| 6 | **Shared** | `services/shared/` | Python 3.12 | Lambda | 공유 Lambda Authorizer (JWT 검증) |

### 1.3 도메인 분리 근거

도메인은 **Bounded Context**(비즈니스 경계)와 **데이터 소유권** 기반으로 분리한다.

```
┌──────────────────────────────────────────────────────────────────────┐
│                         TradingPlatform                               │
│                                                                       │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────────┐  │
│  │  Identity   │  │ SpotTrading│  │ MarketData │  │    Finance     │  │
│  │  (회원/인증) │  │ (현물거래)  │  │  (시세)    │  │   (입출금)     │  │
│  │            │  │            │  │            │  │ ┌────┐┌──────┐ │  │
│  │ - 회원가입  │  │ - 주문 매칭 │  │ - 시세 수집 │  │ │입금 ││ 출금 │ │  │
│  │ - JWT 인증 │  │ - 호가창   │  │ - 캔들 생성 │  │ │    ││      │ │  │
│  │ - TOTP 2FA│  │ - 잔고 관리 │  │ - 실시간WS │  │ │    ││ AML  │ │  │
│  │ - 이메일   │  │ - 체결 알림 │  │ - Kafka   │  │ └────┘└──────┘ │  │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └───────┬────────┘  │
│        │               │               │                  │           │
│        └─── EventBridge ┴── EventBridge ┴── EventBridge ──┘           │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 2. 도메인 분리 및 워크로드 설계

### 2.1 Domain A: Identity (회원/인증)

> **소스**: `services/identity/infra/lambda.tf`, `api_gateway.tf`, `dynamodb.tf`, `ses.tf`, `iam.tf`
> **앱**: `services/identity/app/main.py` — FastAPI + Mangum 어댑터

| 항목 | 선정 | 근거 |
|------|------|------|
| **트래픽 특성** | 버스트형 (로그인 피크), 평시 낮은 요청량 | |
| **API 컴퓨팅** | Lambda (Container Image, 512MB, 30s) | 버스트 트래픽에 Lambda가 비용 효율적. Mangum으로 FastAPI→Lambda 브릿지 |
| **API 게이트웨이** | API Gateway HTTP API | Lambda 통합, JWT Authorizer (300s TTL 캐시) |
| **인증** | Lambda Authorizer (256MB, 5s, ZIP) | RS256 JWT 검증, JWKS 기반 5분 캐시 |
| **Database** | DynamoDB (Single-Table, PAY_PER_REQUEST) | 유저 단건 조회에 1ms 응답. GSI1으로 이메일 lookup. TTL로 토큰 자동 만료 |
| **이메일** | Amazon SES | DKIM 서명, Route53 레코드, 바운스율 5% 알림 |
| **시크릿** | Secrets Manager | JWT private/public key |

**Container Image Lambda를 쓰는 이유**: `cryptography`, `bcrypt`, `pyotp` 패키지가 네이티브 C 확장을 포함하여 ZIP 패키징이 어려움. `public.ecr.aws/lambda/python:3.12` 베이스 이미지 사용.

**API 엔드포인트** (실제 `api_gateway.tf` 기반):

```
Client → API Gateway (HTTP API)
  [공개 라우트 — Authorizer 없음]
  ├── POST /auth/register
  ├── POST /auth/login
  ├── POST /auth/refresh
  ├── POST /auth/logout
  ├── POST /auth/verify-email
  ├── POST /auth/resend-verification
  ├── GET  /auth/.well-known/jwks.json
  └── GET  /health

  [보호 라우트 — JWT Authorizer]
  ├── GET   /users/me
  ├── PATCH /users/me
  ├── POST  /auth/totp/enable
  └── POST  /auth/totp/verify
```

**Batch 워크로드:**

| 작업 | 방식 | 설명 |
|------|------|------|
| 만료 토큰/세션 삭제 | DynamoDB TTL | `ttl` attribute 기반 자동 삭제. 별도 Lambda 불필요 |
| SES 바운스 감시 | CloudWatch Alarm | `Reputation.BounceRate > 5%` → SNS 알림 |

**CI/CD** (`.github/workflows/ci-identity-service.yml`):
- pytest → Docker build → ECR push → Lambda update → **Canary 배포** (10% traffic shift via alias)

---

### 2.2 Domain B: SpotTrading (현물거래)

> **소스**: `services/spot-trading/infra/main.tf`, `infra/environments/prod/spot-trading/main.tf`
> **앱**: `services/spot-trading/app/main.py` — FastAPI + asyncpg + aiokafka + redis
> **매칭 엔진**: `services/spot-trading/app/matching/engine.py`, `order_book.py`

| 항목 | 선정 | 근거 |
|------|------|------|
| **트래픽 특성** | 상시 고빈도, 초저지연 필수, 인메모리 상태 유지 | |
| **API 컴퓨팅** | EKS v1.31 (c6i.xlarge + m6i.large) | 매칭 엔진이 인메모리 오더북 유지. StatefulSet 1 replica |
| **실시간** | API Gateway WebSocket + Lambda 3개 + Redis Pub/Sub | 호가/체결 실시간 스트리밍 |
| **Database** | Aurora PostgreSQL 16.2 (writer + reader, db.r7g.large) | ACID 트랜잭션, 복잡한 JOIN, Performance Insights |
| **Cache** | ElastiCache Redis (cache.r7g.large, 3 shards, cluster mode) | Pub/Sub 브릿지 (REST→WebSocket) |
| **주문 저장** | DynamoDB (`spot-orders`, PAY_PER_REQUEST) | PK/SK + GSI1 + GSI2, Streams(NEW_AND_OLD_IMAGES), PITR |
| **메시징** | Kafka (aiokafka producer) | `spot.orders.v1`, `spot.trades.v1` 토픽 발행 |

**EKS 노드 그룹** (실제 `infra/environments/prod/spot-trading/main.tf`):

| 노드 그룹 | 인스턴스 | 스케일링 | 용도 |
|----------|---------|---------|------|
| `order-engine` | c6i.xlarge (compute-optimized) | min:3 / max:10 | 매칭 엔진 전용. `workload=order-engine:NoSchedule` taint으로 격리 |
| `general` | m6i.large | min:2 / max:8 | API 서버, 모니터링 |

**API 엔드포인트** (실제 `app/routers/` 기반):

```
Client → ALB → EKS Pod (FastAPI)
  ├── POST   /spot/orders                → 주문 생성 (매칭 엔진 호출)
  ├── DELETE /spot/orders/:id            → 주문 취소
  ├── GET    /spot/orders                → 주문 내역
  ├── GET    /spot/orders/:id            → 주문 상세
  ├── GET    /spot/trades                → 체결 내역
  ├── GET    /spot/positions             → 잔고 조회
  ├── GET    /spot/orderbook/:symbol     → 호가창 스냅샷
  └── [Internal — X-Internal-Token 헤더]
      ├── POST /internal/positions/credit   → 입금 잔고 반영
      └── POST /internal/positions/deduct   → 출금 잔고 차감

Client → API Gateway WebSocket
  ├── $connect    → Lambda → DynamoDB (커넥션 저장, 24h TTL)
  ├── $disconnect → Lambda → DynamoDB (커넥션 삭제)
  └── $default    → Lambda → Redis Subscribe → WS Push
```

**Batch 워크로드:**

| 작업 | 방식 | 설명 |
|------|------|------|
| 오더북 복구 | 앱 시작 시 (lifespan) | DB에서 OPEN/PARTIAL 주문 로드 → `engines[symbol].rebuild_from_orders()` |
| 시세 소비 (ACL) | Kafka Consumer (상시 백그라운드) | `market.ticker.v1` 구독, ±10% 가격 검증용 캐시 갱신 |
| Kafka 이벤트 발행 | 주문/체결 후 | DB commit 이후 `acks=all`, `lz4` 압축, 5회 재시도 |

---

### 2.3 Domain C: MarketData (시세)

> **소스**: `services/market-data/infra/main.tf`, `infra/outputs.tf`
> **4개 하위 컴포넌트**: `ingester/`, `router/`, `api/`, `candle-builder/`

| 항목 | 선정 | 근거 |
|------|------|------|
| **트래픽 특성** | 연속 스트리밍 파이프라인, 높은 처리량 | |
| **API 컴퓨팅** | ECS Fargate (FARGATE + FARGATE_SPOT) | 3개 태스크 (ingester, router, api). Spot으로 비용 절감 |
| **스트리밍** | MSK Kafka (3 brokers, KRaft 3.7.x, kafka.t3.small) | TLS+IAM 인증, 100GB EBS/broker, Prometheus 모니터링 |
| **실시간** | API Gateway WebSocket + Lambda 3개 | 클라이언트 시세 스트리밍 |
| **캔들 생성** | Lambda (MSK trigger, batch=100, 5s window) | `bisect_batch_on_error=true` 로 포이즌 메시지 격리 |
| **Database** | DynamoDB (candles: PK/SK + GSI1, PITR, KMS) | OHLCV 시계열 데이터 |
| **Cache** | ElastiCache Redis (cache.r7g.medium, allkeys-lru) | 최신 시세 캐시, multi-AZ |

**4개 하위 컴포넌트 아키텍처:**

```
[External Exchange]
       │
       ↓ WebSocket
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   Ingester    │────→│  MSK Kafka   │────→│    Router     │
│ (ECS Fargate) │     │  (3 brokers) │     │ (ECS Fargate) │
│               │     │  KRaft mode  │     │               │
│ Binance WS →  │     │              │     │ → Redis write │
│ Kafka produce │     │ Topics:      │     │ → EventBridge │
└──────────────┘     │ ticker.v1    │     └──────────────┘
                      │ orderbook.v1 │
                      │ trades.v1    │     ┌──────────────┐
                      │              │────→│ Candle Builder│
                      └──────────────┘     │  (Lambda)     │
                                           │ MSK trigger   │
                                           │ batch=100     │
                                           │ → DynamoDB    │
                                           └──────────────┘

                      ┌──────────────┐
                      │     API       │
                      │ (ECS Fargate) │
                      │ FastAPI       │
                      │ /market/*     │
                      │ Redis + Dynamo│
                      └──────────────┘

                      ┌──────────────┐
                      │  WS Gateway   │
                      │ (API GW + λ)  │
                      │ 실시간 스트림   │
                      └──────────────┘
```

**API 엔드포인트** (실제 `api/app/main.py` 기반):

```
Client → ECS Fargate (FastAPI)
  ├── GET /market/ticker/:symbol     → Redis 캐시 조회
  ├── GET /market/orderbook/:symbol  → Redis 캐시 조회
  ├── GET /market/trades/:symbol     → Redis 최근 체결
  ├── GET /market/candles            → DynamoDB OHLCV 조회
  └── GET /market/symbols            → 지원 심볼 목록
```

**Batch 워크로드:**

| 작업 | 방식 | 설명 |
|------|------|------|
| 시세 수집 | Ingester (ECS, 상시) | Binance WebSocket → Kafka produce |
| 이벤트 라우팅 | Router (ECS, 상시) | Kafka consume → Redis + EventBridge |
| 캔들 생성 | Lambda (MSK trigger) | batch_size=100, 5s window, → DynamoDB OHLCV |

**CI/CD** (`.github/workflows/ci-market-data.yml`):
- pytest (ingester/router/api 병렬) → Terraform validate + Checkov → Docker build (3 이미지) → ECS rolling deploy

---

### 2.4 Domain D: Deposit (입금)

> **소스**: `services/deposit/infra/ecs.tf`, `aurora.tf`, `step_functions.tf`, `eventbridge.tf`, `sqs.tf`
> **앱**: `services/deposit/app/main.py` — FastAPI + asyncpg + boto3 (Step Functions, EventBridge)

| 항목 | 선정 | 근거 |
|------|------|------|
| **트래픽 특성** | 상시 운영, 블록체인 웹훅 수신 필요, 워크플로 기반 | |
| **API 컴퓨팅** | ECS Fargate (512 CPU, 1024 MB) | desired_count=2 (prod), 1 (dev) |
| **워크플로** | Step Functions + Lambda 4개 (Container Image) | 입금 확인 → 잔고 반영 → 이벤트 발행 → 실패 처리 |
| **Database** | Aurora PostgreSQL 15.4 (db.r6g.large, 2 instances) | ACID 트랜잭션, deletion_protection=true, 7일 백업 |
| **Queue** | SQS + DLQ | deposit-tasks (300s visibility), deposit-dlq (14일, maxReceiveCount=3) |
| **이벤트** | EventBridge (`finance-events` 버스) | DepositConfirmed → SpotTrading + Notification 크로스 어카운트 |
| **시크릿** | Secrets Manager 3개 | DB_URL, INTERNAL_TOKEN, WEBHOOK_HMAC_SECRET |

**API 엔드포인트:**

```
Client → API Gateway → ECS Fargate (FastAPI, port 8000)
  ├── POST /deposits/crypto          → 암호화폐 입금 요청
  ├── POST /deposits/fiat            → 법정화폐 입금 요청
  ├── GET  /deposits/:id             → 입금 상태 조회
  ├── GET  /deposits                  → 입금 내역
  ├── GET  /deposits/networks        → 지원 네트워크 조회
  ├── GET  /deposits/address         → 입금 주소 조회
  └── POST /webhook/callback         → 블록체인 확인 콜백 (HMAC 검증)
```

**인증**: `X-User-Id` 헤더 추출 (API Gateway가 Authorizer context에서 주입). `/internal/`, `/health` 경로는 skip.

**Batch 워크로드 — Step Functions (4 States):**

```
┌─────────────────────────────────────────────────┐
│  Deposit Workflow State Machine                  │
│                                                  │
│  CheckConfirmations ──→ CreditBalance            │
│  (블록체인 컨펌 확인)    (잔고 반영)               │
│         │                     │                  │
│    (컨펌 부족)                 ↓                  │
│         │             PublishEvent               │
│    Wait + Retry       (DepositConfirmed)         │
│                              │                   │
│                         (실패 시)                  │
│                              ↓                   │
│                       HandleFailure              │
└─────────────────────────────────────────────────┘
```

4개 Lambda Worker는 **단일 ECR 이미지**(deposit-workers)에서 `CMD`만 다르게 설정:

```hcl
# services/deposit/infra/step_functions.tf
image_config { command = ["workers.check_confirmations.handler"] }
image_config { command = ["workers.credit_balance.handler"] }
image_config { command = ["workers.publish_event.handler"] }
image_config { command = ["workers.handle_failure.handler"] }
```

---

### 2.5 Domain E: Withdrawal (출금)

> **소스**: `services/withdrawal/infra/step_functions.tf`, `eventbridge.tf`, `iam.tf`
> **앱**: `services/withdrawal/app/main.py` — FastAPI + asyncpg + AML service

| 항목 | 선정 | 근거 |
|------|------|------|
| **트래픽 특성** | 금융 트랜잭션, AML 필수, 잔고 예약(lock) 패턴 | |
| **API 컴퓨팅** | ECS Fargate | Deposit과 동일 Finance 어카운트에서 운영 |
| **워크플로** | Step Functions + Lambda 6개 | AML 검증 분기 포함, Deposit보다 복잡 |
| **Database** | Aurora PostgreSQL (Deposit과 공유) | 동일 `finance` 데이터베이스 |
| **이벤트** | EventBridge (`finance-events` 버스 — Deposit이 생성, 공유) | WithdrawalExecuted → RiskCompliance + Notification |

**API 엔드포인트:**

```
Client → API Gateway → ECS Fargate (FastAPI)
  ├── POST /withdrawals/crypto        → 암호화폐 출금 요청
  ├── POST /withdrawals/fiat          → 법정화폐 출금 요청
  ├── GET  /withdrawals/:id           → 출금 상태 조회
  ├── POST /withdrawals/:id/cancel    → 출금 취소
  ├── POST /withdrawals/submit        → 출금 확정
  └── GET  /withdrawals/fee           → 출금 수수료 조회
```

**Batch 워크로드 — Step Functions (6 States + AML 분기):**

```
┌─────────────────────────────────────────────────────┐
│  Withdrawal Workflow State Machine                   │
│                                                      │
│  ReserveBalance ──→ ValidateAML ──┬──→ ExecuteWithdrawal
│  (잔고 lock)        (AML 검증)     │        │         │
│                                   │        ↓         │
│                              (AML 실패)  PublishEvent │
│                                   │  (WithdrawalExecuted)
│                                   ↓        │         │
│                             RejectWithdrawal│         │
│                                             │         │
│                                    (실행 실패) ↓         │
│                                        FailWithdrawal │
└─────────────────────────────────────────────────────┘
```

**IAM** (실제 `services/withdrawal/infra/iam.tf`):
- ECS Task Role: `states:StartExecution`, `events:PutEvents`, `secretsmanager:GetSecretValue`
- Step Functions Role: `lambda:InvokeFunction` — 6개 worker Lambda ARN으로 scope 제한

**Deposit vs Withdrawal 차이:**

| | Deposit | Withdrawal |
|---|---|---|
| Lambda Workers | 4개 | 6개 (AML 검증 + 거절/실패 분기) |
| EventBridge 타겟 | SpotTrading + Notification | RiskCompliance + Notification |
| 잔고 처리 | credit (입금 반영) | reserve → deduct (예약 → 차감) |
| EventBridge 버스 | 생성 (`finance-events`) | 공유 (Deposit이 생성한 버스 재사용) |

---

### 2.6 Shared: Lambda Authorizer

> **소스**: `services/shared/lambda-authorizer/handler.py`

| 항목 | 설명 |
|------|------|
| **역할** | 모든 서비스의 API Gateway에서 공유하는 JWT 검증 Lambda |
| **타입** | REQUEST type Authorizer |
| **특징** | `Authorization` 헤더 + `?token=` 쿼리스트링 지원 (WebSocket 호환) |
| **IAM** | DynamoDB `GetItem`만 허용 (토큰 폐기 확인용) |
| **배포** | 각 서비스 어카운트에 복제 배포 |

---

### 2.7 워크로드 선정 기준 요약

```
                     워크로드 선정 Decision Tree
───────────────────────────────────────────────────────
트래픽 패턴?
  ├── 버스트형 (비활성 시 0) ──→ Lambda         ← Identity
  ├── 연속 스트리밍 파이프라인 ──→ ECS Fargate    ← MarketData
  ├── 상시 + 인메모리 상태 ────→ EKS StatefulSet ← SpotTrading
  └── 상시 + 워크플로 기반 ────→ ECS + Step Func ← Deposit, Withdrawal

데이터 접근 패턴?
  ├── Key-Value 단건 조회 ─────→ DynamoDB   ← Identity, WS connections
  ├── 시계열 OHLCV ────────────→ DynamoDB   ← MarketData candles
  ├── 관계형 JOIN + ACID ──────→ Aurora PG  ← SpotTrading, Finance
  └── 고처리량 이벤트 스트림 ───→ MSK Kafka  ← MarketData

도메인 간 통신?
  ├── 비동기 비즈니스 이벤트 ──→ EventBridge ← Deposit→SpotTrading
  ├── 고처리량 데이터 스트림 ──→ Kafka       ← MarketData→SpotTrading
  └── 실시간 클라이언트 푸시 ──→ Redis Pub/Sub + WebSocket
```

---

## 3. 멀티 어카운트 아키텍처

### 3.1 AWS Organizations 구조

> **소스**: `infra/org/main.tf` — Organizations, 4개 OU, 4개 SCP, Tag Policy, Cost Categories

도메인 1개당 어카운트 1개, prod/dev 환경 분리. Finance(Deposit+Withdrawal)는 동일 어카운트에서 운영.

```
AWS Organizations (Management Account: mgmt)
│
├── OU: Infrastructure
│   ├── infra-network     (Transit Gateway, Network Firewall, Route53)
│   └── infra-security    (GuardDuty 위임, CloudTrail 집중, Security Hub)
│
├── OU: Production
│   ├── a01-identity-prod       (회원/인증 도메인)
│   ├── b01-spot-trading-prod   (현물거래 도메인)
│   ├── c01-market-data-prod    (시세 데이터 도메인)
│   ├── d01-finance-prod        (입출금 도메인 — Deposit + Withdrawal)
│   └── [추가 도메인 어카운트]
│       ├── futures-trading-prod
│       ├── notification-prod
│       └── risk-compliance-prod
│
├── OU: Development
│   ├── a02-identity-dev
│   ├── b02-spot-trading-dev
│   ├── c02-market-data-dev
│   ├── d02-finance-dev
│   └── [추가 도메인 어카운트 dev]
│
└── OU: Security
    └── security-audit    (로그 아카이브, 보안 감사)
```

> **실제 프로젝트에 존재하는 전체 도메인** (`infra/org/main.tf` Tag Policy 기반):
> SpotTrading, FuturesTrading, Deposit, Withdrawal, Identity, MarketData, Notification, RiskCompliance, Security, Network, Shared

### 3.2 어카운트별 VPC CIDR 설계

> **소스**: `infra/environments/prod/spot-trading/main.tf` — `10.10.0.0/16`
> `infra/environments/prod/market-data/main.tf` — `10.1.0.0/16` (account-factory 모듈 사용)

각 어카운트에 **VPC 1개**, CIDR 겹침 없음.

| 어카운트 | 도메인 | VPC CIDR | Public Subnets | Private Subnets |
|---------|--------|----------|----------------|-----------------|
| infra-network | Network | 100.64.0.0/22 | 100.64.0.0/26 ×3 AZ | 100.64.1.0/26 ×3 AZ |
| a01 | Identity (Prod) | 10.1.0.0/16 | 10.1.128.0/20 ×3 | 10.1.0.0/19 ×3 |
| a02 | Identity (Dev) | 10.2.0.0/16 | 10.2.128.0/20 ×3 | 10.2.0.0/19 ×3 |
| b01 | SpotTrading (Prod) | 10.10.0.0/16 | 10.10.128.0/20 ×3 | 10.10.0.0/19 ×3 |
| b02 | SpotTrading (Dev) | 10.20.0.0/16 | 10.20.128.0/20 ×3 | 10.20.0.0/19 ×3 |
| c01 | MarketData (Prod) | 10.30.0.0/16 | 10.30.128.0/20 ×3 | 10.30.0.0/19 ×3 |
| c02 | MarketData (Dev) | 10.40.0.0/16 | 10.40.128.0/20 ×3 | 10.40.0.0/19 ×3 |
| d01 | Finance (Prod) | 10.100.0.0/16 | 10.100.128.0/20 ×3 | 10.100.0.0/19 ×3 |
| d02 | Finance (Dev) | 10.200.0.0/16 | 10.200.128.0/20 ×3 | 10.200.0.0/19 ×3 |

**CIDR 규칙**: Prod는 `10.{1,10,30,100}.0.0/16`, Dev는 `10.{2,20,40,200}.0.0/16`. Inspection VPC는 RFC 6598 대역 `100.64.0.0/22`.

---

## 4. 인프라 네트워크 설계 (4-Tier)

### 4.1 4-Tier 아키텍처

```
Tier 1: Edge / Ingress
  CloudFront + WAF (CLOUDFRONT scope)
  → DDoS 방어, 정적 콘텐츠 캐시, 지리적 제한
                    ↓
Tier 2: DMZ / Load Balancing
  ALB (Public Subnet) + WAF (REGIONAL scope)
  또는 API Gateway (Identity, WebSocket)
  → SSL 종단, 경로 기반 라우팅, Rate Limiting
                    ↓
Tier 3: Application
  Private Subnet
  → EKS Pod / ECS Fargate Task / Lambda Function
  → 인터넷 직접 접근 불가, NAT Gateway 경유
                    ↓
Tier 4: Data
  DB Subnet (격리)
  → Aurora PG / DynamoDB VPC Endpoint / ElastiCache Redis / MSK Kafka
  → App 서브넷에서만 접근 가능
```

### 4.2 Transit Gateway 중앙 허브

> **소스**: `infra/modules/network/main.tf` — Transit Gateway (ASN 64512), Inspection VPC, Network Firewall

```
                          infra-network 어카운트
                    ┌──────────────────────────────┐
                    │     Transit Gateway            │
                    │     (ASN 64512)                 │
                    │     RAM으로 OU에 공유            │
                    │                                │
                    │  ┌────────────────────────┐    │
                    │  │   Inspection VPC        │    │
                    │  │   100.64.0.0/22         │    │
                    │  │                         │    │
                    │  │  AWS Network Firewall   │    │
                    │  │  (Suricata 규칙)        │    │
                    │  └────────────────────────┘    │
                    │                                │
                    │  ┌──────────────────┐          │
                    │  │ rt-prod-spokes   │          │
                    │  │ a01,b01,c01,d01  │          │
                    │  └──────────────────┘          │
                    │  ┌──────────────────┐          │
                    │  │ rt-dev-spokes    │          │
                    │  │ a02,b02,c02,d02  │          │
                    │  └──────────────────┘          │
                    └──────────────────────────────┘

       PROD 어카운트들                        DEV 어카운트들
  ┌────┐┌────┐┌────┐┌────┐            ┌────┐┌────┐┌────┐┌────┐
  │a01 ││b01 ││c01 ││d01 │            │a02 ││b02 ││c02 ││d02 │
  │ID  ││Spot││Mkt ││Fin │            │ID  ││Spot││Mkt ││Fin │
  └─┬──┘└─┬──┘└─┬──┘└─┬──┘            └─┬──┘└─┬──┘└─┬──┘└─┬──┘
    │      │     │     │                  │     │     │     │
    └──────┴─────┴──┬──┘                  └─────┴─────┴──┬──┘
                    │                                     │
              rt-prod-spokes                        rt-dev-spokes
                    │                                     │
                    └──────────┐    ┌─────────────────────┘
                               ↓    ↓
                         Transit Gateway
                               │
                        Inspection VPC
                      (Network Firewall)

  ══════════════════════════════════════════════════════════
  ▲ rt-prod에 dev CIDR 없음. rt-dev에 prod CIDR 없음.     ▲
  ▲ prod ↔ dev 간 라우트 자체가 부재 → 통신 원천 불가      ▲
  ══════════════════════════════════════════════════════════
```

### 4.3 AWS Network Firewall 규칙

> **소스**: `infra/modules/network/main.tf` — Suricata stateful rule groups
> `infra/modules/network/variables.tf` — `allowed_egress_domains`

```python
# 허용된 외부 도메인 (실제 variables.tf)
allowed_egress_domains = [
  ".amazonaws.com",
  ".binance.com",
  ".coingecko.com",
  ".twilio.com",
  ".sendgrid.net",
  ".datadog.com",
  ".datadoghq.com",
  ".pagerduty.com"
]

# Suricata 위협 시그니처 (실제 main.tf)
drop tls → .onion domains       # TOR hidden services 차단
drop dns → .coin domains        # 크립토마이너 DNS 차단
drop http → wp-admin             # WordPress 익스플로잇 차단

# Firewall 로깅
ALERT 로그: 90일 보관 (CloudWatch)
FLOW 로그:  30일 보관 (CloudWatch)
```

### 4.4 인바운드/아웃바운드 Security Group 제어

> **소스**: `services/spot-trading/infra/main.tf` — sg rules
> `services/market-data/infra/main.tf` — MSK, Redis, ECS, Lambda SG

```
┌─────────────────────────────────────────────────────────────────────┐
│  a01 (Identity)                                                      │
│  sg-identity-lambda:                                                 │
│    Out: TCP 443 → DynamoDB/SecretsManager/SES VPC Endpoints         │
├─────────────────────────────────────────────────────────────────────┤
│  b01 (SpotTrading)                                                   │
│  sg-spot-app (EKS):                                                  │
│    In:  TCP 8000 ← sg-spot-alb                                      │
│    Out: TCP 5432 → sg-spot-db                                       │
│         TCP 6379 → sg-spot-redis                                    │
│  sg-spot-db (Aurora):                                                │
│    In:  TCP 5432 ← sg-spot-app (EKS nodes만)                       │
│  sg-spot-redis:                                                      │
│    In:  TCP 6379 ← sg-spot-app + sg-ws-lambda                      │
├─────────────────────────────────────────────────────────────────────┤
│  c01 (MarketData)                                                    │
│  sg-mkt-ecs (ECS Fargate):                                           │
│    In:  TCP 8000/8080 ← ALB                                         │
│    Out: TCP 9094 → sg-mkt-msk (Kafka TLS)                          │
│         TCP 6379 → sg-mkt-redis                                     │
│  sg-mkt-msk (MSK Kafka):                                            │
│    In:  TCP 9094 ← sg-mkt-ecs + sg-candle-lambda                   │
│  sg-mkt-redis:                                                       │
│    In:  TCP 6379 ← sg-mkt-ecs + sg-ws-lambda                       │
├─────────────────────────────────────────────────────────────────────┤
│  d01 (Finance)                                                       │
│  sg-finance-app (ECS):                                               │
│    Out: TCP 5432 → sg-finance-db                                    │
│         TCP 443  → SQS/StepFunc VPC Endpoints                      │
│         TCP 443  → 10.10.0.0/16 (SpotTrading 내부 API, TGW 경유)   │
│  sg-finance-db (Aurora):                                             │
│    In:  TCP 5432 ← sg-finance-app + sg-step-fn-lambda              │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.5 prod↔dev 격리 — 3중 방어

> **소스**: `infra/org/main.tf` lines 147-200 — SCP `DenyProdDevNetworkPeering`

| 레이어 | 메커니즘 | 소스 |
|--------|---------|------|
| 1. TGW 라우팅 | prod RT에 dev CIDR 없음 | `infra/modules/network/main.tf` |
| 2. Network Firewall | Suricata drop rule | `infra/modules/network/main.tf` |
| 3. SCP | TGW 피어링 API 차단 | `infra/org/main.tf` DenyProdDevNetworkPeering |

```hcl
# 실제 SCP (infra/org/main.tf)
resource "aws_organizations_policy" "deny_prod_dev_peering" {
  name = "DenyProdDevNetworkPeering"
  content = jsonencode({
    Statement = [{
      Sid    = "DenyTGWPeeringAcrossEnvs"
      Effect = "Deny"
      Action = [
        "ec2:CreateTransitGatewayPeeringAttachment",
        "ec2:AcceptTransitGatewayPeeringAttachment",
      ]
      Resource = "*"
    }]
  })
}
# Production OU + Development OU 양쪽에 attach
```

### 4.6 전체 네트워크 다이어그램

```
                                Internet
                                   │
                            ┌──────┴──────┐
                            │  CloudFront  │  Tier 1
                            │  + WAF       │
                            └──────┬──────┘
            ┌──────────────────────┼────────────────────────┐
            │            │         │          │              │
      a01(Identity) b01(Spot)  c01(Market) d01(Finance)
     ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐
     │ API GW   │ │   ALB    │ │   ALB    │ │   ALB    │   Tier 2
     │ HTTP API │ │          │ │          │ │          │
     ├──────────┤ ├──────────┤ ├──────────┤ ├──────────┤
     │ Lambda   │ │ EKS Pods │ │ECS×3 +λ │ │ECS Farg. │   Tier 3
     │ (Mangum) │ │ +WS λ×3 │ │candle-λ │ │+SF λ×10 │
     ├──────────┤ ├──────────┤ ├──────────┤ ├──────────┤
     │ DynamoDB │ │Aurora PG │ │MSK Kafka │ │Aurora PG │   Tier 4
     │ SES      │ │Redis     │ │Redis     │ │SQS+DLQ  │
     │ Secrets  │ │DynamoDB  │ │DynamoDB  │ │EventBrdg │
     └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘
          │            │            │             │
          └────────────┴─────┬──────┴─────────────┘
                             │
                       Transit Gateway
                             │
                      Inspection VPC
                    (Network Firewall)
                             │
                       Transit Gateway
                             │
          ┌────────────┬─────┴──────┬─────────────┐
          │            │            │             │
     a02(ID-dev)  b02(Spot-dev) c02(Mkt-dev) d02(Fin-dev)
     축소 스펙      축소 스펙      축소 스펙     축소 스펙
```

---

## 5. EventBridge 크로스 어카운트 이벤트 설계

### 5.1 이벤트 버스 구성

> **소스**: `infra/modules/account-factory/main.tf` — 도메인별 커스텀 버스 자동 생성
> `services/deposit/infra/eventbridge.tf`, `services/withdrawal/infra/eventbridge.tf`

`account-factory` 모듈이 각 어카운트에 도메인 전용 EventBridge 버스를 자동 생성한다.

| 어카운트 | 버스 이름 | 소유 | 비고 |
|---------|----------|------|------|
| a01 | `identity-events` | Identity | |
| b01 | `spot-trading-events` | SpotTrading | |
| c01 | `market-data-events` | MarketData | |
| d01 | `finance-events` | Deposit 생성, Withdrawal 공유 | 입출금 공용 |

### 5.2 크로스 어카운트 이벤트 흐름

```
┌────────────────────────────────────────────────────────────────────┐
│                  이벤트 흐름 (Production)                            │
│                                                                     │
│  [d01] Finance — Deposit                                            │
│    source: "finance.deposit"                                        │
│    detail-type: "DepositConfirmed"                                  │
│        ├──→ [b01] spot-trading-events   (잔고 credit 반영)           │
│        └──→ [★]   notification-events   (사용자 입금 완료 알림)       │
│                                                                     │
│  [d01] Finance — Withdrawal                                         │
│    source: "finance.withdrawal"                                     │
│    detail-type: "WithdrawalExecuted"                                │
│        ├──→ [★]   riskcompliance-events (사후 AML 분석)              │
│        └──→ [★]   notification-events   (사용자 출금 완료 알림)       │
│                                                                     │
│  [c01] MarketData — Router                                          │
│    source: "market-data.router"                                     │
│        └──→ [b01] spot-trading-events   (시세 이벤트)                │
│                                                                     │
│  ★ = 별도 어카운트 (Notification, RiskCompliance)                    │
└────────────────────────────────────────────────────────────────────┘
```

### 5.3 크로스 어카운트 EventBridge 구현

> **소스**: `services/deposit/infra/eventbridge.tf`

**발신 측 (d01 Finance):**

```hcl
resource "aws_cloudwatch_event_bus" "finance" {
  name = "${var.env}-finance-events"
}

resource "aws_cloudwatch_event_rule" "deposit_confirmed" {
  name           = "${var.env}-deposit-confirmed"
  event_bus_name = aws_cloudwatch_event_bus.finance.name
  event_pattern  = jsonencode({
    source      = ["finance.deposit"]
    detail-type = ["DepositConfirmed"]
  })
}

# 크로스 어카운트 타겟
resource "aws_cloudwatch_event_target" "to_spot_trading" {
  rule      = aws_cloudwatch_event_rule.deposit_confirmed.name
  target_id = "spot-trading-bus"
  arn       = var.spot_trading_event_bus_arn  # b01 어카운트 버스 ARN
  role_arn  = aws_iam_role.eventbridge_cross_account.arn
}

resource "aws_cloudwatch_event_target" "to_notification" {
  rule      = aws_cloudwatch_event_rule.deposit_confirmed.name
  target_id = "notification-bus"
  arn       = var.notification_event_bus_arn
  role_arn  = aws_iam_role.eventbridge_cross_account.arn
}
```

**수신 측 (b01 SpotTrading) — account-factory에서 자동 생성:**

```hcl
# infra/modules/account-factory/main.tf
resource "aws_cloudwatch_event_bus_policy" "org_access" {
  event_bus_name = aws_cloudwatch_event_bus.domain.name
  policy = jsonencode({
    Statement = [{
      Sid       = "AllowOrgPutEvents"
      Effect    = "Allow"
      Principal = "*"
      Action    = "events:PutEvents"
      Resource  = aws_cloudwatch_event_bus.domain.arn
      Condition = {
        StringEquals = { "aws:PrincipalOrgID" = var.organization_id }
      }
    }]
  })
}
```

---

## 6. 워크로드(스택)별 구현

### 6.1 API 워크로드 — 전체 서비스 비교

| 서비스 | 컴퓨팅 | API 타입 | 인증 | 엔드포인트 수 | 소스 |
|--------|--------|---------|------|-------------|------|
| **Identity** | Lambda (512MB, Image) | API GW HTTP | JWT Authorizer (300s TTL) | 12 | `services/identity/infra/lambda.tf` |
| **SpotTrading** | EKS c6i.xlarge | ALB + WS API GW | X-User-Id 헤더 + Internal Token | 9 REST + 3 WS | `services/spot-trading/infra/main.tf` |
| **MarketData** | ECS Fargate ×3 | ALB + WS API GW | 공개 (읽기 전용) | 5 REST + 3 WS | `services/market-data/infra/main.tf` |
| **Deposit** | ECS Fargate (512/1024) | ALB | X-User-Id 헤더 | 6 + webhook | `services/deposit/infra/ecs.tf` |
| **Withdrawal** | ECS Fargate | ALB | X-User-Id 헤더 | 6 | `services/withdrawal/infra/` |

### 6.2 Batch 워크로드 — 전체 서비스 비교

| 서비스 | 방식 | 작업 | Workers | 소스 |
|--------|------|------|---------|------|
| **Identity** | DynamoDB TTL + CW Alarm | 토큰 만료, 바운스 감시 | 0 | `services/identity/infra/dynamodb.tf` |
| **SpotTrading** | Kafka Consumer + 시작 시 복구 | ACL 시세 캐시, 오더북 rebuild | 0 (앱 내장) | `services/spot-trading/app/main.py` |
| **MarketData** | ECS 상시 + Lambda MSK trigger | Ingester, Router, Candle Builder | 1 Lambda | `services/market-data/infra/main.tf` |
| **Deposit** | Step Functions | 4 states (확인→반영→발행→실패) | 4 Lambda (단일 이미지) | `services/deposit/infra/step_functions.tf` |
| **Withdrawal** | Step Functions | 6 states (예약→AML→실행→발행→거절→실패) | 6 Lambda | `services/withdrawal/infra/step_functions.tf` |

### 6.3 CI/CD 파이프라인

> **소스**: `.github/workflows/`

| 파이프라인 | 트리거 | 테스트 | 보안 스캔 | 배포 방식 |
|-----------|--------|--------|----------|----------|
| `ci-identity-service.yml` | `services/identity/**` | pytest + moto | — | **Canary** (10% alias) |
| `ci-market-data.yml` | `services/market-data/**` | pytest ×3 (병렬) | Checkov IaC | **ECS Rolling** |
| `ci-infra.yml` | `infra/**` | terraform validate | Checkov | **terraform apply** (main) |
| `ci-frontend.yml` | `apps/web/**` | lint + test + build | — | **Vercel** (Preview/Prod) |

---

## 7. Tag Policy

### 7.1 필수 태그 정의

> **소스**: `infra/org/main.tf` lines 206-281 — `RequiredTags` Tag Policy
> Organizations Root에 attach → 모든 어카운트에 강제 적용

| 태그 키 | 허용 값 | 적용 리소스 | 용도 |
|--------|---------|-----------|------|
| `Company` | `TradingPlatform` | EC2, VPC, ECS, Lambda, RDS, ElastiCache, MSK, EKS, S3 | 전사 식별 |
| `Environment` | `prod`, `dev`, `staging` | 위와 동일 | 환경 분류 |
| `Domain` | `Identity`, `SpotTrading`, `MarketData`, `Deposit`, `Withdrawal`, `FuturesTrading`, `Notification`, `RiskCompliance`, `Security`, `Network`, `Shared` | EC2, ECS, Lambda, RDS, ElastiCache, MSK, EKS | 도메인 분류 |
| `CostCenter` | `CC-IDENTITY`, `CC-SPOT`, `CC-MARKET`, `CC-DEPOSIT`, `CC-WITHDRAW`, `CC-FUTURES`, `CC-NOTIFY`, `CC-RISK`, `CC-SECURITY`, `CC-NETWORK`, `CC-SHARED` | 위와 동일 | 비용 센터 |
| `Team` | `backend`, `frontend`, `infra`, `security`, `data` | EC2, ECS, Lambda | 팀 분류 |
| `ManagedBy` | `terraform`, `manual` | EC2, VPC, ECS, Lambda, RDS, EKS | IaC 관리 여부 |

### 7.2 조직 계층 구조와 태그 매핑

> **소스**: `infra/org/locals.tf` — domain_cost_centers

```
TradingPlatform (Company)
│
├── Trading Division (거래 본부)
│   ├── SpotTrading Team      ← Domain: SpotTrading,     CostCenter: CC-SPOT
│   ├── FuturesTrading Team   ← Domain: FuturesTrading,  CostCenter: CC-FUTURES
│   └── MarketData Team       ← Domain: MarketData,      CostCenter: CC-MARKET
│
├── Finance Division (금융 본부)
│   ├── Deposit Team          ← Domain: Deposit,         CostCenter: CC-DEPOSIT
│   └── Withdrawal Team       ← Domain: Withdrawal,      CostCenter: CC-WITHDRAW
│
├── Platform Division (플랫폼 본부)
│   ├── Identity Team         ← Domain: Identity,        CostCenter: CC-IDENTITY
│   ├── Notification Team     ← Domain: Notification,    CostCenter: CC-NOTIFY
│   └── RiskCompliance Team   ← Domain: RiskCompliance,  CostCenter: CC-RISK
│
└── Infra Division (인프라 본부)
    ├── Network Team          ← Domain: Network,         CostCenter: CC-NETWORK
    └── Security Team         ← Domain: Security,        CostCenter: CC-SECURITY
```

### 7.3 전체 어카운트 태그 매핑

| 어카운트 | Company | Domain | CostCenter | Team | Environment |
|---------|---------|--------|------------|------|-------------|
| a01 | TradingPlatform | Identity | CC-IDENTITY | backend | prod |
| a02 | TradingPlatform | Identity | CC-IDENTITY | backend | dev |
| b01 | TradingPlatform | SpotTrading | CC-SPOT | backend | prod |
| b02 | TradingPlatform | SpotTrading | CC-SPOT | backend | dev |
| c01 | TradingPlatform | MarketData | CC-MARKET | data | prod |
| c02 | TradingPlatform | MarketData | CC-MARKET | data | dev |
| d01 (Deposit) | TradingPlatform | Deposit | CC-DEPOSIT | backend | prod |
| d01 (Withdrawal) | TradingPlatform | Withdrawal | CC-WITHDRAW | backend | prod |
| d02 | TradingPlatform | Deposit/Withdrawal | CC-DEPOSIT/WITHDRAW | backend | dev |
| infra-net | TradingPlatform | Network | CC-NETWORK | infra | prod |
| infra-sec | TradingPlatform | Security | CC-SECURITY | security | prod |

### 7.4 Cost Categories (3-Level 계층)

> **소스**: `infra/org/main.tf` lines 288-355

```hcl
# Level 1: Company
resource "aws_ce_cost_category" "by_company" {
  name = "Company"
  rule { value = "TradingPlatform"
    rule { tags { key = "Company"; values = ["TradingPlatform"] } }
  }
  default_value = "Untagged"
}

# Level 2: Domain (CostCenter 태그 기반, dynamic block)
resource "aws_ce_cost_category" "by_domain" {
  name = "Domain"
  dynamic "rule" {
    for_each = local.domain_cost_centers
    # SpotTrading→CC-SPOT, Deposit→CC-DEPOSIT, ...
    content {
      value = rule.key
      rule { tags { key = "CostCenter"; values = [rule.value] } }
    }
  }
  default_value = "Untagged"
}

# Level 3: Environment
resource "aws_ce_cost_category" "by_environment" {
  name = "Environment"
  rule { value = "Production"
    rule { tags { key = "Environment"; values = ["prod"] } }
  }
  rule { value = "Development"
    rule { tags { key = "Environment"; values = ["dev", "staging"] } }
  }
  default_value = "Untagged"
}
```

---

## 8. 비용 가시화 (Cost Visibility)

### 8.1 요구사항

> 상위 조직별로 비용을 볼 수 있어야 한다.
> 예: Deposit팀의 상위 조직인 Finance Division에는 Withdrawal팀도 있다.
> Finance Division으로 취합 시 리소스 갯수 및 비용이 한눈에 보여야 한다.

### 8.2 Cost Explorer 쿼리 매핑

| 질문 | Group By | Filter |
|------|----------|--------|
| 전사 비용? | — | Company = TradingPlatform |
| Trading Division 비용? | CostCenter | CostCenter IN (CC-SPOT, CC-FUTURES, CC-MARKET) |
| Finance Division 비용? | CostCenter | CostCenter IN (CC-DEPOSIT, CC-WITHDRAW) |
| SpotTrading DB 비용? | — | CostCenter=CC-SPOT, 서비스=RDS |
| Prod vs Dev 비용? | Environment | — |
| 도메인별 Lambda 비용? | Domain | 서비스=Lambda |

### 8.3 비용 가시화 대시보드

```
┌──────────────────────────────────────────────────────────────────────┐
│                TradingPlatform 월간 비용 대시보드                      │
│                                                                       │
│  전사 합계: $15,800/month                                             │
│                                                                       │
│  ┌─── Trading Division ────────────────────────────────────────────┐  │
│  │  합계: $8,200 (51.9%)                                           │  │
│  │                                                                  │  │
│  │  SpotTrading (CC-SPOT): $5,500                                  │  │
│  │  ├── EKS (c6i.xlarge ×3~10 + m6i.large ×2~8)   $2,800         │  │
│  │  ├── Aurora PG (r7g.large ×2)                    $1,400         │  │
│  │  ├── Redis (r7g.large, 3 shards)                 $900           │  │
│  │  ├── Lambda (WS handlers ×3)                     $50            │  │
│  │  └── DynamoDB + etc                               $350          │  │
│  │                                                                  │  │
│  │  MarketData (CC-MARKET): $2,200                                 │  │
│  │  ├── MSK Kafka (t3.small ×3, 100GB EBS)          $600           │  │
│  │  ├── ECS Fargate (ingester + router + api)        $500          │  │
│  │  ├── Redis (r7g.medium)                           $400          │  │
│  │  ├── Lambda (candle-builder + WS ×3)              $100          │  │
│  │  └── DynamoDB + etc                               $600          │  │
│  │                                                                  │  │
│  │  FuturesTrading (CC-FUTURES): $500 (개발 중)                     │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌─── Finance Division ────────────────────────────────────────────┐  │
│  │  합계: $4,200 (26.6%)                                           │  │
│  │                                                                  │  │
│  │  Deposit (CC-DEPOSIT): $2,500                                   │  │
│  │  ├── ECS Fargate (512/1024 ×2 tasks)              $450          │  │
│  │  ├── Aurora PG (r6g.large ×2, 공유)               $1,200        │  │
│  │  ├── Step Functions + Lambda ×4                   $90            │  │
│  │  ├── SQS (tasks + DLQ)                            $20           │  │
│  │  └── EventBridge + Secrets + etc                  $740          │  │
│  │                                                                  │  │
│  │  Withdrawal (CC-WITHDRAW): $1,700                               │  │
│  │  ├── ECS Fargate                                  $350          │  │
│  │  ├── Aurora PG (Deposit과 공유)                   (공유)         │  │
│  │  ├── Step Functions + Lambda ×6                   $120          │  │
│  │  └── EventBridge + etc                            $1,230        │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌─── Platform Division ───────────────────────────────────────────┐  │
│  │  합계: $2,000 (12.7%)                                           │  │
│  │                                                                  │  │
│  │  Identity (CC-IDENTITY): $850                                   │  │
│  │  ├── Lambda (512MB, Container Image)              $120          │  │
│  │  ├── Lambda Authorizer (256MB)                    $40           │  │
│  │  ├── API Gateway                                  $30           │  │
│  │  ├── DynamoDB (PAY_PER_REQUEST)                   $200          │  │
│  │  ├── SES                                          $10           │  │
│  │  └── Secrets Manager + etc                        $450          │  │
│  │                                                                  │  │
│  │  Notification + RiskCompliance: $1,150                          │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                                                       │
│  ┌─── Infra Division ──────────────────────────────────────────────┐  │
│  │  합계: $1,400 (8.9%)                                            │  │
│  │  Network (CC-NETWORK): Transit GW + Network FW + NAT GW        │  │
│  │  Security (CC-SECURITY): GuardDuty + CloudTrail + Security Hub │  │
│  └──────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 9. 리소스 가시화 (Resource Visibility)

### 9.1 요구사항

> 상위 조직별로 가지고 있는 리소스를 한눈에 볼 수 있어야 한다.

### 9.2 AWS Resource Groups (태그 기반)

```hcl
# Finance Division 전체 리소스 그룹
resource "aws_resourcegroups_group" "finance_division" {
  name = "finance-division-all"
  resource_query {
    query = jsonencode({
      ResourceTypeFilters = ["AWS::AllSupported"]
      TagFilters = [{
        Key    = "CostCenter"
        Values = ["CC-DEPOSIT", "CC-WITHDRAW"]
      }]
    })
  }
}

# Trading Division 전체 리소스 그룹
resource "aws_resourcegroups_group" "trading_division" {
  name = "trading-division-all"
  resource_query {
    query = jsonencode({
      ResourceTypeFilters = ["AWS::AllSupported"]
      TagFilters = [{
        Key    = "CostCenter"
        Values = ["CC-SPOT", "CC-FUTURES", "CC-MARKET"]
      }]
    })
  }
}
```

### 9.3 AWS Config Aggregator (멀티 어카운트 중앙 조회)

```hcl
resource "aws_config_configuration_aggregator" "org" {
  name = "trading-platform-aggregator"
  organization_aggregation_source {
    all_regions = true
    role_arn    = aws_iam_role.config_aggregator.arn
  }
}
```

### 9.4 리소스 가시화 대시보드

```
┌──────────────────────────────────────────────────────────────────────────┐
│                TradingPlatform 리소스 가시화 대시보드 (Prod)               │
│                                                                           │
│  ┌─── Trading Division ──────────────────────────────────────────────┐   │
│  │  총 리소스: 35개                                                    │   │
│  │                                                                     │   │
│  │  SpotTrading (18개)              MarketData (17개)                  │   │
│  │  ├─ EKS Cluster        1        ├─ ECS Cluster         1           │   │
│  │  ├─ EKS Node Groups    2        ├─ ECS Services        3           │   │
│  │  ├─ Aurora PG Cluster  1(2inst) ├─ MSK Kafka Cluster   1(3broker) │   │
│  │  ├─ Redis Cluster      1(3shard)├─ Redis               1(1+1repl) │   │
│  │  ├─ DynamoDB Tables    2        ├─ DynamoDB Tables      2           │   │
│  │  ├─ Lambda Functions   3(WS)    ├─ Lambda Functions     4(WS+candle)│  │
│  │  ├─ WS API Gateway     1        ├─ WS API Gateway       1           │   │
│  │  └─ VPC + SG + etc     8        └─ VPC + SG + etc       5           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                           │
│  ┌─── Finance Division ──────────────────────────────────────────────┐   │
│  │  총 리소스: 25개                                                    │   │
│  │                                                                     │   │
│  │  Deposit (15개)                  Withdrawal (10개)                  │   │
│  │  ├─ ECS Cluster        1        ├─ (ECS Deposit과 공유)             │   │
│  │  ├─ ECS Service        1(2task) ├─ Step Functions      1           │   │
│  │  ├─ Aurora PG Cluster  1(2inst) ├─ Lambda Workers      6           │   │
│  │  ├─ Step Functions     1        ├─ EventBridge Rule    1           │   │
│  │  ├─ Lambda Workers     4        ├─ CloudWatch LogGroup 1           │   │
│  │  ├─ SQS Queue          1        ├─ IAM Roles           2           │   │
│  │  ├─ SQS DLQ            1        └─                                 │   │
│  │  ├─ EventBridge Bus    1                                            │   │
│  │  ├─ EventBridge Rule   1                                            │   │
│  │  ├─ Secrets Manager    3                                            │   │
│  │  └─ CloudWatch LogGroup 1                                           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                           │
│  ┌─── Platform Division ─────────────────────────────────────────────┐   │
│  │  총 리소스: 9개                                                     │   │
│  │                                                                     │   │
│  │  Identity (9개)                                                     │   │
│  │  ├─ Lambda Functions    2 (identity-service + authorizer)           │   │
│  │  ├─ API Gateway HTTP    1                                           │   │
│  │  ├─ DynamoDB Table      1 (single-table, GSI1)                      │   │
│  │  ├─ SES Domain Identity 1 (DKIM)                                    │   │
│  │  ├─ Secrets Manager     2 (JWT keys)                                │   │
│  │  ├─ CloudWatch Alarm    1 (SES bounce)                              │   │
│  │  └─ ECR Repository      1                                           │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                           │
│  ┌─── Infra Division ────────────────────────────────────────────────┐   │
│  │  총 리소스: 12개                                                    │   │
│  │  ├─ Transit Gateway     1         ├─ GuardDuty Detectors  8(각 계정)│   │
│  │  ├─ Network Firewall    1         ├─ CloudTrail           8(각 계정)│   │
│  │  ├─ Inspection VPC      1         ├─ KMS CMKs             8(각 계정)│   │
│  │  └─ TGW Route Tables   2(prod/dev)└─ Config Aggregator    1        │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                           │
│  ══════════════════════════════════════════════════════════════════════    │
│  전사 리소스 합계 (Prod):                                                 │
│  ┌──────────────┬──────┬──────┬──────┬──────┬──────┬──────┐              │
│  │ 유형          │ ID   │ Spot │ Mkt  │ Dep  │ Wdl  │ 합계  │              │
│  ├──────────────┼──────┼──────┼──────┼──────┼──────┼──────┤              │
│  │ Lambda       │  2   │  3   │  4   │  4   │  6   │  19  │              │
│  │ ECS Service  │  -   │  -   │  3   │  1   │  -   │  4   │              │
│  │ EKS Cluster  │  -   │  1   │  -   │  -   │  -   │  1   │              │
│  │ Aurora PG    │  -   │  1   │  -   │  1   │ (공유)│  2   │              │
│  │ DynamoDB     │  1   │  2   │  2   │  -   │  -   │  5   │              │
│  │ Redis        │  -   │  1   │  1   │  -   │  -   │  2   │              │
│  │ MSK Kafka    │  -   │  -   │  1   │  -   │  -   │  1   │              │
│  │ Step Func.   │  -   │  -   │  -   │  1   │  1   │  2   │              │
│  │ SQS Queue    │  -   │  -   │  -   │  2   │  -   │  2   │              │
│  │ EventBridge  │  -   │  -   │  -   │  2   │  1   │  3   │              │
│  │ API Gateway  │  1   │  1   │  1   │  -   │  -   │  3   │              │
│  ├──────────────┼──────┼──────┼──────┼──────┼──────┼──────┤              │
│  │ 소계          │  9   │ 18   │ 17   │ 15   │ 10   │ 69   │              │
│  └──────────────┴──────┴──────┴──────┴──────┴──────┴──────┘              │
│  + Infra Division: ~12개 → 전사 총계: ~81개                               │
│  ══════════════════════════════════════════════════════════════════════    │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 부록: 소스 코드 참조 전체 목록

| 항목 | 파일 경로 |
|------|----------|
| **Organizations, SCP, Tag Policy** | `infra/org/main.tf` |
| **Cost Center 매핑** | `infra/org/locals.tf` |
| **리전 제한, 어카운트 ID** | `infra/org/variables.tf` |
| **Transit Gateway, Network Firewall** | `infra/modules/network/main.tf` |
| **도메인 허용 목록** | `infra/modules/network/variables.tf` |
| **Account Factory (VPC, GuardDuty, KMS, EB)** | `infra/modules/account-factory/main.tf` |
| **SpotTrading Prod (EKS, Aurora, Redis, DDB)** | `infra/environments/prod/spot-trading/main.tf` |
| **Identity Lambda, Authorizer** | `services/identity/infra/lambda.tf` |
| **Identity API Gateway** | `services/identity/infra/api_gateway.tf` |
| **Identity DynamoDB** | `services/identity/infra/dynamodb.tf` |
| **Identity SES** | `services/identity/infra/ses.tf` |
| **Identity IAM** | `services/identity/infra/iam.tf` |
| **Identity FastAPI App** | `services/identity/app/main.py` |
| **Identity Authorizer Handler** | `services/identity/authorizer/handler.py` |
| **Shared Authorizer** | `services/shared/lambda-authorizer/handler.py` |
| **SpotTrading Infra (Aurora, Redis, WS)** | `services/spot-trading/infra/main.tf` |
| **SpotTrading App (Matching Engine)** | `services/spot-trading/app/main.py` |
| **SpotTrading OrderBook** | `services/spot-trading/app/matching/order_book.py` |
| **SpotTrading Engine** | `services/spot-trading/app/matching/engine.py` |
| **SpotTrading K8s** | `services/spot-trading/k8s/*.yaml` |
| **SpotTrading WS Notifier** | `services/spot-trading/ws-notifier/` |
| **MarketData Infra (ECS, MSK, Redis, DDB)** | `services/market-data/infra/main.tf` |
| **MarketData Ingester** | `services/market-data/ingester/app/main.py` |
| **MarketData Router** | `services/market-data/router/app/main.py` |
| **MarketData API** | `services/market-data/api/app/main.py` |
| **MarketData Candle Builder** | `services/market-data/candle-builder/` |
| **Deposit ECS** | `services/deposit/infra/ecs.tf` |
| **Deposit Aurora** | `services/deposit/infra/aurora.tf` |
| **Deposit Step Functions** | `services/deposit/infra/step_functions.tf` |
| **Deposit EventBridge** | `services/deposit/infra/eventbridge.tf` |
| **Deposit SQS** | `services/deposit/infra/sqs.tf` |
| **Deposit App** | `services/deposit/app/main.py` |
| **Withdrawal Step Functions** | `services/withdrawal/infra/step_functions.tf` |
| **Withdrawal EventBridge** | `services/withdrawal/infra/eventbridge.tf` |
| **Withdrawal IAM** | `services/withdrawal/infra/iam.tf` |
| **Withdrawal App** | `services/withdrawal/app/main.py` |
| **CI/CD Identity** | `.github/workflows/ci-identity-service.yml` |
| **CI/CD MarketData** | `.github/workflows/ci-market-data.yml` |
| **CI/CD Infra** | `.github/workflows/ci-infra.yml` |
| **CI/CD Frontend** | `.github/workflows/ci-frontend.yml` |
| **Frontend App** | `apps/web/` |
| **Shared Types** | `packages/types/` |
| **Monorepo Config** | `package.json`, `turbo.json`, `pnpm-workspace.yaml` |
