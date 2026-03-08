# Gap Detector Memory

## Project: crypto-trading-platform (Enterprise, DDD)

### Key Architecture Facts
- Go 1.23 services with Clean Architecture: handler -> usecase -> domain -> repository
- Internal comms: gRPC (proto in packages/proto/)
- External API: REST + WebSocket via order-svc
- Event fabric: AWS EventBridge with transactional outbox pattern
- DB: PostgreSQL (trading schema), Redis (order book snapshots)

### Analysis History
- **trading-order-matching** Iteration 1 (2026-03-08): Match Rate 84%, 2 CRITICAL gaps
- **trading-order-matching** Iteration 2 (2026-03-08): Match Rate 95%, PASS
  - All 10 Act-1 fixes verified (2 CRITICAL, 3 HIGH, 5 MEDIUM resolved)
  - 6 LOW gaps remain (doc updates + stop-book future feature + WS filter)
  - Report: docs/03-analysis/trading-order-matching.analysis.md
- **trading-platform** Iteration 1 (2026-03-08): Match Rate 40%, frontend-only
  - Frontend: 93% match (50 full + 4 partial / 56 items)
  - Backend/IaC/K8s/CI-CD: 0% (all 99 items missing)
  - HIGH security gap: tokens persisted to localStorage, design says httpOnly cookie
- **trading-platform** Iteration 2 (2026-03-08): Match Rate 43%, frontend 98%
  - All 4 Act-1 fixes verified: token security, WS auth, exp backoff, PriceChart real data
  - 0 regressions detected
  - Frontend: 55/56 full match (only missing: logout() in identityApi, LOW)
  - Security: 38% (was 19%) -- token storage fix resolved HIGH gap
- **trading-platform** Iteration 3 (2026-03-08): Match Rate 90%, PASS
  - Frontend: 100% (56/56, logout() added)
  - Identity Service: 93% (39/43, missing JWKS endpoint + Redis token revocation)
  - Infrastructure IaC: 83% (42/52, account-factory missing 4-tier subnets + some vars)
  - CI/CD: 85% (15.5/18, missing frontend test step + terraform apply job)
  - Weighted: (100x0.25)+(93x0.30)+(83x0.30)+(85x0.15) = 90.6%
  - Report: docs/03-analysis/trading-platform.analysis.md

- **market-data-service** Iteration 1 (2026-03-08): Match Rate 87.3%, FAIL
  - 4 HIGH gaps: str->float types (G1), timestamp removed (G2), pub/sub channel mismatch (G9), no Pydantic response models (G12)
  - 5 MED gaps: Trade payload key qty vs quantity (G3), float cast in ACL (G8), orderbook member format (G10), pipeline transaction mode (G11)
  - Python services (not Go): ingester, router, api (FastAPI), candle-builder + ws-gateway (Lambda)
  - Terraform IaC: 100% match (MSK, Redis, DynamoDB, API GW all present)
  - Fix G1+G8+G9 alone would bring to ~93%
  - Report: docs/03-analysis/market-data-service.analysis.md

- **spot-trading-service** Iteration 1 (2026-03-08): Match Rate 95.5%, PASS
  - Backend: 98.6% (140/142 items), Frontend: 52% (major architectural change)
  - 2 HIGH gaps: submitOrder/cancelOrder missing from useOrders hook (G10), Zustand vs useReducer (G11)
  - 3 MED gaps: design doc buyer_id bug (G4), matching-engine K8s command (G7), WS message type mismatch "orderUpdate" vs "order_update" (G12)
  - Python service: FastAPI + asyncpg + aiokafka + heapq matching engine
  - All backend components (domain, repos, engine, ACL, producer, routers, Lambda, migration, K8s, Terraform) match design faithfully
  - Frontend hook reimplemented with Zustand store + useWebSocket abstraction instead of raw useReducer + WebSocket
  - Report: docs/03-analysis/spot-trading-service.analysis.md

- **identity-service** Iteration 1 (2026-03-08): Match Rate 99.3%, PASS
  - 140/141 design items matched across all 12 categories
  - Only 1 CHANGED item: make_user fixture -> active_user/pending_user (functionally equivalent)
  - 11 ADDED production enhancements (Lambda perms, Secrets Manager, CW logs, DKIM records, bounce alarm, extra tests, redirect param)
  - Python FastAPI + DynamoDB single-table + RS256 JWT + SES email verification
  - Lambda Authorizer: JWKS cache, access-token-only validation (no DynamoDB revocation for access tokens)
  - Frontend: silent refresh interceptor, initializeAuth boot, Next.js middleware route guard
  - Report: docs/03-analysis/identity-service.analysis.md

- **deposit-service** Iteration 1 (2026-03-08): Match Rate 1.3%, FAIL
  - Entire services/deposit/ directory empty -- 0/87 backend items implemented
  - Spot-trading integration: 0/3, Terraform: 0/10, Frontend: 0.5/10
- **deposit-service** Iteration 2 (2026-03-08): Match Rate 99.0%, PASS
  - All 134 design items verified (87 backend + 7 ASL + 3 spot-trading + 10 IaC + 17 tests + 10 frontend)
  - 133 full match, 1 partial (auth store path/token access pattern -- LOW)
  - 17 ADDED items: 5 IaC enhancements, 7 extra tests, 1 test fixture, 4 legacy frontend functions
  - 0 regressions from pre-existing code
  - Report: docs/03-analysis/deposit-service.analysis.md

- **withdrawal-service** Iteration 1 (2026-03-08): Match Rate 95.5%, PASS
  - 12/15 backend files character-perfect match to design code
  - 1 HIGH gap: missing ecs.tf (ECS task def + service + SG)
  - 1 MED gap: missing test_withdrawals_router.py (HTTP-layer tests)
  - 2 LOW: config.py db_url has local dev default, useWithdrawal.ts renamed inner fn to avoid global fetch shadow
  - Python FastAPI + asyncpg + boto3 (Step Functions + EventBridge) + httpx (spot-trading internal)
  - All 20 design test cases (TC-W01-W16 + TC-A01-A04) implemented and match
  - ASL: 7/7 states exact match, IaC: 4/5 TF files match
  - Spot-trading /internal/positions/deduct endpoint: exact match
  - Frontend: all 4 API functions + useWithdrawal hook + WithdrawPage exact match
  - Report: docs/03-analysis/withdrawal-service.analysis.md

### Common Patterns to Check
- Auth middleware wiring in cmd/server/main.go (easy to forget -- now fixed pattern exists)
- Outbox poller must actually call MarkPublished (verified fix pattern: collect IDs per batch)
- Redis stores assigned to `_` = snapshot never used (check main.go for unused assignments)
- FOK order type: canFullyFill() pre-check pattern is correct approach (no rollback needed)
- Metrics namespace should match service name, not domain (matching_* not trading_*)
- Snapshot save should be async (go saveSnapshot) to avoid blocking matching hot path
- Python market-data: design used `str` for all prices/quantities, impl used `float` -- financial data should stay as strings to avoid precision loss
- Pub/sub channel naming must match between producer (redis_handler) and consumer (ws-gateway) -- easy to miss when patterns differ (ws: vs market:)
- Frontend hooks that redesign state management (useReducer -> Zustand) are common sources of HIGH gaps -- check return value contract carefully
- WS message type naming convention mismatch ("orderUpdate" camelCase vs "order_update" snake_case) -- always verify both ends agree
- Design TF code often omits API GW routes/integrations/permissions -- implementation must add them; count as ADDED not gaps
- apply_trade() buyer_id/seller_id: design code sometimes passes order IDs instead of user IDs -- implementation must resolve via DB lookup
