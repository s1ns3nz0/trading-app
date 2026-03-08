# Plan: deposit-service

> **Feature**: deposit-service
> **Created**: 2026-03-08
> **Phase**: Plan
> **Level**: Enterprise

---

## Executive Summary

| Perspective | Detail |
|-------------|--------|
| **Problem** | Users have no way to fund their trading accounts — spot trading positions are seeded manually with no real balance source, making the platform a demo rather than a functional exchange. |
| **Solution** | Build a deposit service that accepts crypto (on-chain detection via webhook) and fiat (mock bank transfer) deposits, locks them through a Step Functions approval workflow, and credits the user's position balance only after confirmation — connected to the spot-trading service via EventBridge. |
| **Function / UX Effect** | Users initiate a deposit from the frontend, receive a wallet address or bank reference, and see their available balance update automatically once the deposit confirms — all with full audit trail and status visibility. |
| **Core Value** | A financially reliable, auditable deposit pipeline where balance credits are atomic, idempotent, and traceable — providing the foundation for all trading activity and satisfying AML/compliance requirements through a mandatory review step. |

---

## 1. Overview

### 1.1 Background

The trading platform's Finance domain requires two deposit types:

- **Crypto deposits**: User sends crypto to a platform-controlled wallet address; on-chain detection triggers a deposit record and confirmation workflow.
- **Fiat deposits**: User initiates a bank transfer using a reference code; a mock bank webhook (or manual confirmation) triggers the workflow.

Both paths share the same state machine: `PENDING → CONFIRMING → CONFIRMED → CREDITED` (or `FAILED`/`EXPIRED`). The position credit step calls the spot-trading service's internal balance API.

From the trading-platform architecture design:
- **Compute**: ECS Fargate + AWS Step Functions
- **DB**: Aurora PostgreSQL
- **Messaging**: SQS Standard (for Step Functions async tasks)
- **Cross-domain**: EventBridge (`finance.deposit.v1.DepositConfirmed`)

### 1.2 Goals

| ID | Goal | Priority |
|----|------|----------|
| G-01 | User can request a crypto deposit address (ETH/BTC/USDT) | Must |
| G-02 | Webhook receiver detects on-chain confirmation and triggers workflow | Must |
| G-03 | User can initiate a fiat deposit with a bank reference code | Must |
| G-04 | Step Functions state machine manages PENDING→CONFIRMED→CREDITED lifecycle | Must |
| G-05 | Confirmed deposit atomically credits user's position balance | Must |
| G-06 | EventBridge publishes `finance.deposit.v1.DepositConfirmed` on credit | Must |
| G-07 | All deposits stored in Aurora with full audit trail | Must |
| G-08 | Idempotent deposit processing (no double-credit on webhook retry) | Must |
| G-09 | Frontend deposit page with status polling | Should |
| G-10 | Minimum deposit amounts enforced (0.001 ETH, 10 USDT, $10 fiat) | Should |
| G-11 | Deposit expiry — PENDING deposits expire after 24h | Should |
| G-12 | Admin endpoint to manually confirm/reject deposits | Could |

### 1.3 Non-Goals

- Real blockchain node integration (use mock/testnet webhook simulation)
- Real bank payment processor (mock webhook only)
- KYC verification gating (stub — future phase)
- Multi-currency fiat (USD only in v1)
- Withdrawal service (separate PDCA cycle)

---

## 2. Domain Model

```
DepositRequest
├── id: UUID (PK)
├── user_id: str (FK → Identity)
├── type: CRYPTO | FIAT
├── asset: str (ETH | BTC | USDT | USD)
├── amount: Decimal
├── status: PENDING | CONFIRMING | CONFIRMED | CREDITED | FAILED | EXPIRED
├── wallet_address: str | None     (crypto only — platform address)
├── tx_hash: str | None            (crypto only — on-chain tx)
├── bank_reference: str | None     (fiat only)
├── confirmations: int             (crypto only — block confirmations)
├── required_confirmations: int    (e.g., 12 for ETH)
├── step_fn_execution_arn: str | None
├── credited_at: datetime | None
├── expires_at: datetime           (now + 24h)
├── created_at: datetime
└── updated_at: datetime
```

### Status Transitions

```
PENDING ──────────────────────────────────────────► EXPIRED (24h timeout)
   │
   │  on-chain detection / bank webhook
   ▼
CONFIRMING ──────────────────────────────────────► FAILED (on-chain reorg / error)
   │
   │  required confirmations reached / fiat confirmed
   ▼
CONFIRMED
   │
   │  balance credit to spot-trading position
   ▼
CREDITED ─── EventBridge: finance.deposit.v1.DepositConfirmed
```

---

## 3. Architecture

```
Frontend                     Deposit Service (ECS Fargate)
─────────                    ────────────────────────────
POST /deposits/crypto   ──►  Create deposit, return wallet address
POST /deposits/fiat     ──►  Create deposit, return bank reference
GET  /deposits/{id}     ──►  Poll status
GET  /deposits          ──►  List user deposits

Webhook endpoints (internal — not user-facing):
POST /internal/webhooks/crypto  ◄── Blockchain monitor (mock)
POST /internal/webhooks/fiat    ◄── Bank adapter (mock)

Step Functions State Machine:
  WaitForConfirmation → CheckConfirmations → CreditBalance → PublishEvent

Aurora PostgreSQL:
  deposits table (main), deposit_audit_log table

EventBridge:
  finance.deposit.v1.DepositConfirmed → spot-trading account bus
                                      → notification account bus
                                      → riskcompliance account bus
```

### Position Credit Flow

```python
# Deposit service calls Spot Trading internal API after confirmation
POST https://internal.spot-trading.svc/internal/positions/credit
Headers: X-Internal-Token: <shared secret>
Body: { user_id, asset, amount, deposit_id }
# Spot Trading credits available balance (SELECT FOR UPDATE on position row)
```

---

## 4. Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| R-01 | Idempotent webhook processing via deposit `id` or `tx_hash` | Duplicate webhook delivers same result, no double-credit |
| R-02 | Step Functions handles CONFIRMING timeout (24h) | Deposits stuck in CONFIRMING auto-FAIL after 24h |
| R-03 | Credit API call is wrapped in DB transaction with status update | If credit API fails, status stays CONFIRMED (retryable) |
| R-04 | Minimum deposit amounts enforced at API layer | 422 returned for amounts below minimum |
| R-05 | All status changes written to `deposit_audit_log` | Full audit trail for compliance |
| R-06 | Webhook endpoint validates HMAC signature | Unsigned/invalid webhooks return 401 |
| R-07 | EventBridge publish uses idempotency key = deposit_id | Duplicate events filtered by consumer |
| R-08 | Frontend polls `/deposits/{id}` every 10s until terminal state | Status updates reflected in UI |

---

## 5. Implementation Scope

### Step 1 — Domain Model + Alembic Migration
- `app/models/domain.py` — `DepositRequest`, `DepositType`, `DepositStatus` enums
- `migrations/versions/001_initial_schema.py` — `deposits` + `deposit_audit_log` tables

### Step 2 — Repository Layer
- `app/repositories/deposit_repo.py` — `DepositRepository` ABC + `PostgresDepositRepository`
  - `create()`, `get()`, `get_by_tx_hash()`, `update_status()`, `list_by_user()`, `get_expired()`

### Step 3 — Crypto Address Generation (Mock)
- `app/services/wallet_service.py` — `WalletService`
  - `generate_address(asset)` → deterministic address per user+asset (mock HD wallet)
  - `validate_address(address, asset)` → format check

### Step 4 — Deposit Service (Core Logic)
- `app/services/deposit_service.py` — `DepositService`
  - `create_crypto_deposit(user_id, asset, amount)` → DepositRequest
  - `create_fiat_deposit(user_id, amount)` → DepositRequest with bank reference
  - `process_crypto_webhook(tx_hash, address, amount, confirmations)` → triggers Step Fn
  - `process_fiat_webhook(bank_reference, amount)` → triggers Step Fn
  - `credit_balance(deposit_id)` → calls spot-trading internal API
  - `expire_pending_deposits()` → batch expire job

### Step 5 — Step Functions State Machine
- `infra/step_functions.tf` — state machine definition (ASL JSON)
  - States: `WaitForConfirmations`, `CheckConfirmations`, `CreditBalance`, `PublishEvent`, `HandleFailure`
- `app/services/step_fn_service.py` — `StepFnService.start_execution(deposit_id)`

### Step 6 — FastAPI Application
- `app/main.py` — lifespan: DB pool, Step Fn client, EventBridge client
- `app/routers/deposits.py` — user-facing CRUD endpoints
- `app/routers/webhooks.py` — internal webhook endpoints with HMAC validation
- `app/schemas.py` — request/response Pydantic models
- `app/middleware/auth.py` — validates `X-User-Id` from Lambda Authorizer

### Step 7 — EventBridge Integration
- `app/producers/eventbridge_producer.py` — `EventBridgeProducer.publish_deposit_confirmed(deposit)`
  - `source`: `finance.deposit`
  - `detail-type`: `DepositConfirmed`
  - `detail`: `{ deposit_id, user_id, asset, amount, credited_at }`

### Step 8 — Terraform Infrastructure
- `infra/aurora.tf` — Aurora PostgreSQL (db.r6g.large, finance schema)
- `infra/ecs.tf` — ECS Fargate service + task definition
- `infra/step_functions.tf` — Step Functions state machine
- `infra/eventbridge.tf` — EventBridge bus + rules for cross-account routing
- `infra/iam.tf` — ECS task role, Step Functions role, EventBridge role
- `infra/sqs.tf` — Dead letter queue for failed Step Functions tasks

### Step 9 — Tests
- `tests/conftest.py` — mocked Aurora pool, mock spot-trading client
- `tests/test_deposit_service.py` — create, webhook, credit, expire flows
- `tests/test_webhooks.py` — HMAC validation, idempotency

### Step 10 — Frontend
- `apps/web/src/app/(app)/deposit/page.tsx` — deposit initiation form (crypto/fiat tabs)
- `apps/web/src/hooks/useDeposit.ts` — polling hook for deposit status
- `apps/web/src/services/financeApi.ts` — update with deposit endpoints

---

## 6. Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Double-credit on webhook retry | Critical | Unique constraint on `tx_hash`; DB transaction wraps status+credit |
| Step Functions execution cost at scale | Medium | Workflows only start on webhook receipt — not per-poll |
| Spot-trading internal credit API unavailable | High | Retry in Step Functions (3 attempts, exponential backoff); deposit stays CONFIRMED |
| Blockchain reorg invalidates confirmed tx | Medium | Require 12 confirmations before CONFIRMED; FAILED status path in state machine |
| HMAC secret rotation disrupts webhooks | Low | Rotate with 1h overlap window; old+new secrets both accepted during rotation |

---

## 7. Dependencies

| Dependency | Status |
|-----------|--------|
| Identity service (Lambda Authorizer) | Archived ✅ |
| Spot-trading internal credit endpoint | Needs `POST /internal/positions/credit` added |
| Aurora PostgreSQL cluster (finance account) | Terraform needed |
| EventBridge cross-account bus rules | Terraform needed |
| Step Functions IAM roles | Terraform needed |
