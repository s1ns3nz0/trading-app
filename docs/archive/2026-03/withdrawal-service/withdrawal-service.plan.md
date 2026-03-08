# Plan: withdrawal-service

> **Feature**: withdrawal-service
> **Created**: 2026-03-08
> **Phase**: Plan
> **Level**: Enterprise

---

## Executive Summary

| Perspective | Detail |
|-------------|--------|
| **Problem** | Users can deposit funds but have no way to withdraw them — balances are trapped on the platform with no exit mechanism, making the exchange incomplete and unusable for real trading. |
| **Solution** | Build a withdrawal service that deducts balance from spot-trading (reservation), routes requests through a Step Functions approval workflow with AML limit checks, and executes crypto sends or bank transfers — with full reversal on failure. |
| **Function / UX Effect** | Users submit a withdrawal request, see it transition through PENDING → PROCESSING → EXECUTED status in real time, and receive funds at their external wallet or bank account — or see a clear rejection reason if limits or checks fail. |
| **Core Value** | A financially safe, reversible-on-failure withdrawal pipeline where balance reservation is atomic, AML limits are enforced server-side, and every state transition is audited — completing the Finance domain's deposit/withdraw loop. |

---

## 1. Overview

### 1.1 Background

The Finance domain now has deposits (done). Withdrawals are the symmetric counterpart:

- **Crypto withdrawals**: User provides external wallet address; platform hot wallet sends on-chain transaction.
- **Fiat withdrawals**: User provides bank account details; platform initiates ACH/wire transfer (mock).

Both paths share the same lifecycle: `PENDING → PROCESSING → EXECUTED` (or `REJECTED` / `FAILED` / `CANCELLED`).

The key difference from deposits: **balance must be reserved (deducted) before execution and released if execution fails** — money going out is irreversible once on-chain.

From the platform architecture:
- **Compute**: ECS Fargate + AWS Step Functions
- **DB**: Aurora PostgreSQL (finance schema — same cluster as deposits)
- **Cross-domain**: EventBridge (`finance.withdrawal.v1.WithdrawalExecuted`)
- **Balance source**: Spot-trading internal API `POST /internal/positions/deduct`

### 1.2 Goals

| ID | Goal | Priority |
|----|------|----------|
| G-01 | User can request crypto withdrawal (ETH/BTC/USDT) to external address | Must |
| G-02 | User can request fiat withdrawal (USD) to bank account | Must |
| G-03 | Balance reserved atomically before processing starts | Must |
| G-04 | Balance released on REJECTED/FAILED/CANCELLED | Must |
| G-05 | Step Functions workflow: PENDING → PROCESSING → EXECUTED lifecycle | Must |
| G-06 | AML daily withdrawal limit enforced (e.g., $50k USD equivalent) | Must |
| G-07 | Per-transaction minimum/maximum limits enforced at API layer | Must |
| G-08 | All state transitions written to `withdrawal_audit_log` | Must |
| G-09 | EventBridge publishes `finance.withdrawal.v1.WithdrawalExecuted` on EXECUTED | Must |
| G-10 | Idempotent execution (no double-send on retry) | Must |
| G-11 | Frontend withdrawal page with real-time status polling | Should |
| G-12 | Admin endpoint to manually approve/reject large withdrawals | Could |
| G-13 | Crypto address format validation before processing | Should |
| G-14 | Address whitelist / cooldown period for new addresses | Could |

### 1.3 Non-Goals

- Real blockchain transaction signing (mock execution — generate tx_hash)
- Real ACH/wire processing (mock bank adapter)
- KYC gating (stub — future phase)
- Multi-currency fiat (USD only in v1)
- Withdrawal fee calculation (flat $0 in v1 — fee service is separate)

---

## 2. Domain Model

```
WithdrawalRequest
├── id: UUID (PK)
├── user_id: str (FK → Identity)
├── type: CRYPTO | FIAT
├── asset: str (ETH | BTC | USDT | USD)
├── amount: Decimal
├── status: PENDING | PROCESSING | EXECUTED | REJECTED | FAILED | CANCELLED
├── to_address: str | None         (crypto: destination wallet)
├── tx_hash: str | None            (crypto: on-chain tx after execution)
├── bank_account_number: str | None (fiat: destination account)
├── bank_routing_number: str | None (fiat: routing/sort code)
├── rejection_reason: str | None
├── step_fn_execution_arn: str | None
├── reserved_at: datetime | None   (when balance was deducted)
├── executed_at: datetime | None
├── expires_at: datetime           (PENDING expires after 24h)
├── created_at: datetime
└── updated_at: datetime
```

### Status Transitions

```
PENDING ──────────────────────────────────────────► CANCELLED (user cancels before processing)
   │                                              ► EXPIRED (24h timeout — not yet started)
   │  balance reservation success
   ▼
PROCESSING ──────────────────────────────────────► FAILED (balance deduct failed / execution error)
   │                                              ► REJECTED (AML limit exceeded / admin reject)
   │  on-chain tx sent / bank transfer initiated
   ▼
EXECUTED ─── EventBridge: finance.withdrawal.v1.WithdrawalExecuted
              → balance NOT released (already sent)

On FAILED/REJECTED: balance deduction reversed (credit back)
```

---

## 3. Architecture

```
Frontend                      Withdrawal Service (ECS Fargate)
────────                      ────────────────────────────────
POST /withdrawals/crypto  ──► Validate → Reserve balance → Start Step Fn
POST /withdrawals/fiat    ──► Validate → Reserve balance → Start Step Fn
GET  /withdrawals/{id}    ──► Poll status
GET  /withdrawals         ──► List user withdrawals
DELETE /withdrawals/{id}  ──► Cancel PENDING withdrawal + release balance

Step Functions State Machine:
  ValidateAndAML → ExecuteCrypto|ExecuteFiat → PublishEvent → Done
                ↓ (AML fail / admin reject)
             Reject → ReleaseBalance

Spot-Trading Internal API:
POST /internal/positions/deduct  ← reserve (deduct available)
POST /internal/positions/credit  ← release (credit back on failure)

EventBridge:
  finance.withdrawal.v1.WithdrawalExecuted → riskcompliance account bus
                                           → notification account bus
```

### AML Limit Enforcement

```python
# Daily rolling window per user:
# SELECT SUM(amount) FROM withdrawals
# WHERE user_id = $1 AND status = 'EXECUTED'
#   AND created_at >= NOW() - INTERVAL '24 hours'
# If sum + new_amount > DAILY_LIMIT_USD → REJECT
```

### Balance Flow

```
                    ┌─ EXECUTED ─► balance gone (no reversal)
Reserve → DEDUCT ───┤
                    └─ FAILED/REJECTED ─► CREDIT back (reversal)
```

---

## 4. Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| R-01 | Balance reservation is atomic with status → PROCESSING | If deduct fails, status stays PENDING, no Step Fn started |
| R-02 | AML daily limit check inside Step Functions (re-checked at execution time) | Withdrawal rejected if 24h rolling sum exceeds $50k |
| R-03 | EXECUTED state is terminal — balance NOT released | On-chain tx is irreversible; reversal only on FAILED/REJECTED |
| R-04 | Cancel only allowed in PENDING state | 409 returned if cancel attempted on PROCESSING/EXECUTED |
| R-05 | Crypto address validated before processing (format + not blocklisted) | Invalid address → 422 at API layer |
| R-06 | Minimum withdrawal amounts enforced | 0.001 ETH, 0.0001 BTC, 10 USDT, $10 USD |
| R-07 | Maximum per-transaction limits enforced | 10 ETH, 1 BTC, 50,000 USDT, $50,000 USD |
| R-08 | All status changes written to `withdrawal_audit_log` | Full trail for compliance |
| R-09 | EventBridge uses idempotency key = withdrawal_id | No duplicate events to downstream |
| R-10 | Step Functions execution name = withdrawal_id (idempotency) | Duplicate start raises ExecutionAlreadyExists |

---

## 5. Implementation Scope

### Step 1 — Domain Model + Alembic Migration
- `app/models/domain.py` — `WithdrawalRequest`, `WithdrawalType`, `WithdrawalStatus`
- `migrations/versions/001_initial_schema.py` — `withdrawals` + `withdrawal_audit_log` tables

### Step 2 — Repository Layer
- `app/repositories/withdrawal_repo.py` — `WithdrawalRepository` ABC + `PostgresWithdrawalRepository`
  - `create()`, `get()`, `update_status()`, `list_by_user()`, `get_daily_executed_sum()`, `get_cancellable()`

### Step 3 — AML Service
- `app/services/aml_service.py` — `AMLService`
  - `check_daily_limit(user_id, asset, amount)` → bool
  - `DAILY_LIMIT_USD`: dict per asset using approximate exchange rates
  - `usd_equivalent(asset, amount)` → Decimal

### Step 4 — Withdrawal Service (Core Logic)
- `app/services/withdrawal_service.py` — `WithdrawalService`
  - `create_crypto_withdrawal(user_id, asset, amount, to_address)` → WithdrawalRequest
  - `create_fiat_withdrawal(user_id, amount, bank_account, bank_routing)` → WithdrawalRequest
  - `reserve_balance(withdrawal_id)` → calls spot-trading `/internal/positions/deduct`
  - `execute_crypto(withdrawal_id)` → mock on-chain send, sets tx_hash
  - `execute_fiat(withdrawal_id)` → mock bank transfer
  - `reject_withdrawal(withdrawal_id, reason)` → releases balance
  - `cancel_withdrawal(withdrawal_id, user_id)` → PENDING only, releases balance
  - `fail_withdrawal(withdrawal_id, reason)` → releases balance

### Step 5 — Step Functions State Machine
- `infra/step_functions_asl.json` — ASL definition
  - States: `ReserveBalance`, `ValidateAML`, `ExecuteWithdrawal`, `PublishEvent`, `Reject`, `ReleaseBalance`
- `app/services/step_fn_service.py` — `StepFnService.start_execution(withdrawal_id)`

### Step 6 — Spot-Trading: Internal Deduct Endpoint
- `services/spot-trading/app/routers/internal.py` — add `POST /internal/positions/deduct`
  - Uses `PositionRepository.lock_for_order()` pattern (deduct from available)

### Step 7 — FastAPI Application
- `app/main.py` — lifespan: DB pool, Step Fn client, EventBridge client
- `app/routers/withdrawals.py` — user-facing CRUD (create, get, list, cancel)
- `app/schemas.py` — request/response Pydantic models
- `app/middleware/auth.py` — validates `X-User-Id` from Lambda Authorizer

### Step 8 — EventBridge Integration
- `app/producers/eventbridge_producer.py` — `EventBridgeProducer.publish_withdrawal_executed(withdrawal)`
  - Source: `finance.withdrawal`, DetailType: `WithdrawalExecuted`

### Step 9 — Terraform Infrastructure
- `infra/ecs.tf` — ECS Fargate (shares Aurora cluster with deposit)
- `infra/step_functions.tf` — Step Functions state machine
- `infra/eventbridge.tf` — finance-events bus rules for WithdrawalExecuted
- `infra/iam.tf` — ECS task role, Step Fn role
- `infra/variables.tf`

### Step 10 — Tests
- `tests/conftest.py` — mocked pool, mock spot-trading client, fixtures
- `tests/test_withdrawal_service.py` — create, reserve, execute, reject, cancel, AML flows
- `tests/test_aml_service.py` — limit check logic

### Step 11 — Frontend
- `apps/web/src/app/(app)/withdraw/page.tsx` — withdrawal form (crypto/fiat tabs)
- `apps/web/src/hooks/useWithdrawal.ts` — polling hook (10s, stops on terminal)
- `apps/web/src/services/financeApi.ts` — add withdrawal endpoints

---

## 6. Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Double-execution of on-chain send | Critical | Step Fn idempotency (execution name = withdrawal_id); tx_hash unique constraint |
| Balance deducted but Step Fn fails to start | High | Deduct and Step Fn start in same compensating transaction; FAILED releases balance |
| AML check at request time stale by execution time | Medium | Re-check AML inside Step Functions at execution state (double check) |
| User cancels while PROCESSING | Low | Cancel only allowed in PENDING; 409 in PROCESSING |
| Hot wallet insufficient funds | Medium | Check hot wallet balance before execute; FAILED + release if insufficient |

---

## 7. Dependencies

| Dependency | Status |
|-----------|--------|
| Identity service (Lambda Authorizer) | Archived ✅ |
| Spot-trading `POST /internal/positions/deduct` | Needs adding to `internal.py` |
| Deposit service Aurora cluster (finance schema) | Available ✅ |
| EventBridge finance-events bus | Deployed with deposit-service ✅ |
| Step Functions IAM roles | Needs new state machine |
