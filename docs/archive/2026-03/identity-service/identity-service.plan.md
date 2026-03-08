# Plan: identity-service

> **Feature**: identity-service
> **Created**: 2026-03-08
> **Phase**: Plan
> **Level**: Enterprise

---

## Executive Summary

| Perspective | Detail |
|-------------|--------|
| **Problem** | The trading platform's services (spot-trading, market-data) currently trust `X-User-Id` as a plain HTTP header — any caller can forge an identity. Without a real authentication boundary, every API is wide open to impersonation attacks. |
| **Solution** | Complete the identity service with a JWT Lambda Authorizer that validates RS256 tokens at the API Gateway layer before requests reach any backend service, eliminating the trusted-header anti-pattern across the platform. |
| **Function / UX Effect** | Users get a secure register → email-verify → login → TOTP-enroll flow with short-lived access tokens (1h) and rotating refresh tokens (7d) stored in httpOnly cookies; downstream services receive a verified `X-User-Id` header automatically injected by the authorizer. |
| **Core Value** | A single, auditable authentication boundary that every microservice in the platform inherits for free — no per-service auth logic, no header-spoofing risk, and a clear compliance trail for KYC/AML requirements. |

---

## 1. Overview

### 1.1 Background

The identity service codebase already exists (`services/identity/`) with:
- FastAPI application with `Mangum` Lambda adapter
- `User` domain model (DynamoDB single-table design, GSI1 on email)
- `AuthService`: register, login (constant-time comparison, TOTP), refresh, logout
- `JWTAuthMiddleware` (RS256, `request.state.user_id`)
- `/auth/register`, `/auth/login`, `/auth/refresh`, `/auth/logout`
- `/auth/totp/enable`, `/auth/totp/verify`
- `/auth/.well-known/jwks.json`
- `/users/me` (GET, PATCH)
- DynamoDB Terraform (`infra/dynamodb.tf`) with KMS, PITR, TTL, GSI1

**What is missing**:
1. Lambda Authorizer function (critical — other services need this)
2. API Gateway + Lambda deployment Terraform (no deployment path)
3. Email verification flow (`PENDING_VERIFICATION` status never resolves)
4. Refresh token revocation (no blacklist)
5. Rate limiting on auth endpoints (brute-force protection)
6. Tests (tests/ directory is empty)
7. Frontend auth integration (login page, token storage, refresh logic)

### 1.2 Goals

| ID | Goal | Priority |
|----|------|----------|
| G-01 | Lambda Authorizer validates JWT and injects `X-User-Id` into upstream requests | Must |
| G-02 | API Gateway + Lambda Terraform for identity service deployment | Must |
| G-03 | Email verification endpoint that activates `PENDING_VERIFICATION` accounts | Must |
| G-04 | Refresh token revocation via DynamoDB blocklist (logout invalidates token) | Must |
| G-05 | Rate limiting on `/auth/login` and `/auth/register` via API GW usage plan | Must |
| G-06 | Unit + integration tests for AuthService and repository | Must |
| G-07 | Frontend auth flow: login page, token refresh interceptor, protected routes | Should |
| G-08 | KYC stub endpoint (`/users/me/kyc`) to support deposit/withdrawal gating | Could |

### 1.3 Non-Goals

- Full KYC provider integration (Jumio, Onfido) — stub only
- SMS-based MFA (TOTP via app only)
- Social login (Google, GitHub OAuth) — future phase
- Password reset via email — future phase (scope creep)

---

## 2. Domain Model

```
User
├── id: UUID (PK)
├── email: str (GSI1 lookup key)
├── username: str
├── hashed_password: str (bcrypt, 12 rounds)
├── status: PENDING_VERIFICATION | ACTIVE | SUSPENDED
├── totp_secret: str | None
├── totp_enabled: bool
├── created_at: datetime
└── updated_at: datetime

VerificationToken (DynamoDB item, TTL 24h)
├── PK: VTOKEN#{token}
├── SK: VERIFY
├── user_id: str
└── ttl: unix timestamp (+24h)

RevokedToken (DynamoDB item, TTL = token exp)
├── PK: REVOKED#{jti}
├── SK: REFRESH
└── ttl: unix timestamp (token exp)
```

### DynamoDB Access Patterns

| Access Pattern | Key |
|----------------|-----|
| Get user by ID | PK=`USER#{id}`, SK=`PROFILE` |
| Get user by email | GSI1: `EMAIL#{email}` |
| Get verification token | PK=`VTOKEN#{token}`, SK=`VERIFY` |
| Check revoked JTI | PK=`REVOKED#{jti}`, SK=`REFRESH` |

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    API Gateway (HTTP API)                    │
│                                                             │
│  /auth/*  ──── NO authorizer (public)                       │
│  /users/* ──── Lambda Authorizer → Identity Lambda          │
│                                                             │
│  /spot/*  ──── Lambda Authorizer → Spot Trading EKS         │
│  /market/* ─── Lambda Authorizer → Market Data ECS          │
└──────────────────┬──────────────────────────────────────────┘
                   │ authorizer validates JWT
                   ▼
         ┌─────────────────────┐
         │  Lambda Authorizer  │
         │                     │
         │ 1. Decode JWT header │
         │ 2. Fetch JWKS from  │
         │    identity service │
         │ 3. Verify RS256 sig │
         │ 4. Check not revoked│
         │ 5. Return Allow +   │
         │    X-User-Id context│
         └─────────────────────┘
                   │
                   ▼
         ┌─────────────────────┐
         │  Identity Lambda    │ (Mangum → FastAPI)
         │  (existing code)    │
         │                     │
         │  DynamoDB           │
         │  SES (email verify) │
         └─────────────────────┘
```

### Token Flow

```
Register → email → verify_email → ACTIVE

Login(email, password, [totp]) → (access_token, refresh_token_cookie)
  access_token: RS256 JWT, 1h, in-memory (localStorage NOT used)
  refresh_token: RS256 JWT, 7d, httpOnly cookie, path=/auth/refresh

POST /auth/refresh → rotate: new (access, refresh) pair
                   → old refresh jti added to RevokedToken table

POST /auth/logout  → revoke current refresh jti
                   → clear cookie
```

---

## 4. Requirements

| ID | Requirement | Acceptance Criteria |
|----|-------------|---------------------|
| R-01 | Lambda Authorizer rejects requests with invalid/expired JWT | 401 returned before request reaches downstream service |
| R-02 | Lambda Authorizer injects verified `X-User-Id` context header | Downstream service reads header, never trusts client-provided value |
| R-03 | JWKS cached in Lambda Authorizer memory (TTL 5min) | Authorizer does not call identity service on every request |
| R-04 | Email verification token expires in 24h | DynamoDB TTL auto-deletes; re-request available |
| R-05 | Refresh token rotation — old jti revoked on every `/auth/refresh` | Stolen refresh token cannot be reused after legitimate refresh |
| R-06 | Login blocked after 5 consecutive failures (per email, 15min window) | Return 429, DynamoDB counter with TTL |
| R-07 | All auth endpoints respond within 500ms p99 (Lambda cold start excluded) | Measured via CloudWatch |
| R-08 | Tests cover register/login/refresh/revoke/totp flows | pytest coverage ≥ 80% on services/ |

---

## 5. Implementation Scope

### Step 1 — Refresh Token Revocation (RevokedToken in DynamoDB)
- Add `RevokedToken` items on logout and token refresh
- Check revocation in `AuthService.refresh()`
- DynamoDB TTL auto-cleans expired entries

### Step 2 — Email Verification Flow
- Add `VerificationToken` DynamoDB items (24h TTL)
- `POST /auth/verify-email?token=xxx` endpoint
- AWS SES send on register (mocked in dev with env flag)
- Blocked login for `PENDING_VERIFICATION` accounts

### Step 3 — Rate Limiting
- DynamoDB `LOGIN_ATTEMPT#{email}` counter + TTL (15min)
- Block after 5 failures with 429 + retry-after header

### Step 4 — Lambda Authorizer
- Standalone Lambda function (`services/identity/authorizer/handler.py`)
- Fetches JWKS from `GET /auth/.well-known/jwks.json`
- In-memory cache with 5min TTL
- Checks `RevokedToken` table for refresh tokens
- Returns IAM policy `Allow` + `context: { userId: <sub> }`

### Step 5 — Terraform: API Gateway + Lambda
- `infra/api_gateway.tf` — HTTP API with Lambda integrations and authorizer
- `infra/lambda.tf` — Identity Lambda + Authorizer Lambda (separate functions)
- `infra/iam.tf` — execution roles, DynamoDB + SES permissions
- `infra/ses.tf` — SES identity verification for send domain

### Step 6 — Tests
- `tests/test_auth_service.py` — register, login, TOTP, revocation, rate limit
- `tests/test_repository.py` — mocked DynamoDB (moto)
- `tests/test_authorizer.py` — valid/expired/revoked/malformed JWT cases

### Step 7 — Frontend Auth Integration
- `apps/web/src/app/(auth)/login/page.tsx` — login form
- `apps/web/src/app/(auth)/register/page.tsx` — register form
- `apps/web/src/lib/auth/token.ts` — in-memory access token store
- `apps/web/src/lib/auth/refresh.ts` — axios interceptor for silent refresh
- `apps/web/src/middleware.ts` — Next.js route guard (redirect unauthenticated)

---

## 6. Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Lambda cold start adds auth latency | Medium | Provisioned concurrency for authorizer (always-warm) |
| JWKS fetch failure blocks all requests | High | Authorizer caches last known JWKS; falls back to deny on fetch error |
| DynamoDB revocation list grows unbounded | Low | TTL auto-expires entries at token expiry time |
| bcrypt cost (12 rounds) under load | Medium | Lambda memory = 512MB; bcrypt is CPU-bound, acceptable at 12 rounds |
| SES in sandbox limits email delivery | Low | Dev flag bypasses SES; prod requires SES production access request |

---

## 7. Dependencies

| Dependency | Status |
|-----------|--------|
| DynamoDB table (`trading-identity`) | Terraform exists (`infra/dynamodb.tf`) |
| AWS SES verified domain | Not yet provisioned |
| API Gateway HTTP API | Not yet provisioned |
| RS256 key pair | Must be generated and stored in Secrets Manager |
| `apps/web/` Next.js app | Exists — auth pages need to be wired |
