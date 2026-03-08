# Plan: trading-platform

> **Feature**: trading-platform
> **Created**: 2026-03-08
> **Phase**: Plan
> **Level**: Enterprise

---

## Executive Summary

| Perspective | Detail |
|-------------|--------|
| **Problem** | Building a production-grade crypto trading platform requires clearly separated domain boundaries (DDD), cross-account AWS isolation, and cost visibility by business unit — all of which are difficult to achieve without explicit architectural upfront decisions. |
| **Solution** | Adopt a DDD microservices architecture with one AWS account per domain, EventBridge for cross-account event flow, AWS Network Firewall for traffic inspection, and Terraform Factory pattern to enforce consistent security baselines across all accounts. |
| **Function / UX Effect** | Each engineering team owns their domain account independently; platform teams can onboard new domains by supplying variables to the factory module with no manual security setup; finance can drill cost reports down to individual microservice level via tag-based Cost Categories. |
| **Core Value** | A scalable, auditable, and financially transparent crypto trading infrastructure where security posture is enforced by infrastructure code — not by human discipline — and costs are traceable from company level down to individual service level. |

---

## 1. Overview

### 1.1 Background

A crypto trading platform requires strict separation of concerns at both the **software** and **infrastructure** level. The three initial features (Deposit, Spot Trading, Futures Trading) are only the core — a production system also requires Identity, Market Data, Notifications, and Risk/Compliance domains to be viable.

The organization is structured vertically (departments → services), which creates requirements for:
- Per-domain AWS account isolation (blast radius reduction)
- Cross-account event-driven communication (decoupled integration)
- Hierarchical cost reporting (department → service granularity)
- Enforced security baselines (no manual drift possible)

### 1.2 Goals

| ID | Goal | Priority |
|----|------|----------|
| G-01 | Define complete DDD domain hierarchy for crypto trading | Must |
| G-02 | Design AWS multi-account architecture with one VPC per domain | Must |
| G-03 | Cross-account event communication via EventBridge | Must |
| G-04 | All inter-account traffic monitored via AWS Network Firewall | Must |
| G-05 | Dev and Prod environments physically isolated (no network path) | Must |
| G-06 | Tag policy enabling cost reporting at department and service level | Must |
| G-07 | IaC and application codebases in separate repositories | Must |
| G-08 | Terraform Factory pattern for consistent account provisioning | Must |

### 1.3 Non-Goals

- Application-level code implementation (out of scope for this plan — IaC focus)
- Kubernetes manifest design (Phase 2 / Design phase)
- CI/CD pipeline implementation details
- Database schema design per domain

---

## 2. Domain Hierarchy (DDD Bounded Contexts)

```
CryptoTradingPlatform (Organization Root)
│
├── Trading Department                [CostCenter: CC-TRD]
│   ├── SpotTrading                   [CostCenter: CC-TRD-SPOT]
│   └── FuturesTrading                [CostCenter: CC-TRD-FUT]
│
├── Finance Department                [CostCenter: CC-FIN]
│   ├── Deposit                       [CostCenter: CC-FIN-DEP]
│   └── Withdrawal                    [CostCenter: CC-FIN-WDR]
│
└── Platform Department               [CostCenter: CC-PLT]
    ├── Identity                      [CostCenter: CC-PLT-IDN]
    ├── MarketData                    [CostCenter: CC-PLT-MKT]
    ├── Notification                  [CostCenter: CC-PLT-NOT]
    └── RiskCompliance                [CostCenter: CC-PLT-RSK]
```

### Domain Definitions

| Domain | Type | Responsibility | Key Entities |
|--------|------|---------------|--------------|
| **SpotTrading** | Core | Buy/sell at current market price; order matching | Order, Trade, OrderBook |
| **FuturesTrading** | Core | Derivatives trading; leverage, margin, liquidation | Position, Contract, Margin |
| **Deposit** | Core | Fiat & crypto deposit processing and confirmation | DepositRequest, Transaction |
| **Withdrawal** | Core | Fiat & crypto withdrawal processing and compliance | WithdrawalRequest, KYC check |
| **Identity** | Supporting | User registration, authentication, KYC verification | User, Session, KYCRecord |
| **MarketData** | Supporting | Real-time price feeds, order books, OHLCV candles | Ticker, Candle, OrderBookSnapshot |
| **Notification** | Generic | Email, push, SMS alerts triggered by domain events | NotificationJob, Template |
| **RiskCompliance** | Generic | AML monitoring, fraud detection, position limits | RiskRule, AuditLog, ComplianceReport |

### Key DDD Rules

- Each bounded context owns its own data model — `Order` in SpotTrading ≠ `Order` in FuturesTrading
- Cross-domain integration ONLY via published domain events (never shared database)
- EventBridge Schema Registry enforces event contracts between domains
- Anti-Corruption Layer (ACL) pattern when consuming external exchange APIs in MarketData

---

## 3. AWS Multi-Account Architecture

### 3.1 Account Structure

```
AWS Organizations Root (Management Account)
│
├── OU: Security
│   ├── security-prod     ← GuardDuty delegated admin, Security Hub aggregator, Config aggregator
│   └── log-archive-prod  ← Centralized S3 for CloudTrail, VPC Flow Logs, Config history
│
├── OU: Infrastructure
│   ├── network-prod      ← Transit Gateway (prod), centralized egress VPC, Route53 Resolver
│   └── shared-services   ← ECR, CodePipeline/CodeBuild, Artifact Registry
│
├── OU: Production        ← SCP: DenyAllDevVpcRoutes, DenyDevAccountActions
│   ├── identity-prod          VPC CIDR: 10.0.0.0/16
│   ├── marketdata-prod        VPC CIDR: 10.1.0.0/16
│   ├── spottrading-prod       VPC CIDR: 10.2.0.0/16
│   ├── futurestrading-prod    VPC CIDR: 10.3.0.0/16
│   ├── deposit-prod           VPC CIDR: 10.4.0.0/16
│   ├── withdrawal-prod        VPC CIDR: 10.5.0.0/16
│   ├── notification-prod      VPC CIDR: 10.6.0.0/16
│   └── riskcompliance-prod    VPC CIDR: 10.7.0.0/16
│
└── OU: Development       ← SCP: DenyAllProdVpcRoutes, DenyProdAccountActions
    ├── identity-dev           VPC CIDR: 10.100.0.0/16
    ├── marketdata-dev         VPC CIDR: 10.101.0.0/16
    ├── spottrading-dev        VPC CIDR: 10.102.0.0/16
    ├── futurestrading-dev     VPC CIDR: 10.103.0.0/16
    ├── deposit-dev            VPC CIDR: 10.104.0.0/16
    ├── withdrawal-dev         VPC CIDR: 10.105.0.0/16
    ├── notification-dev       VPC CIDR: 10.106.0.0/16
    └── riskcompliance-dev     VPC CIDR: 10.107.0.0/16
```

### 3.2 AWS Workload Selection per Domain

| Domain | Compute | Primary DB | Cache | Messaging | Rationale |
|--------|---------|-----------|-------|-----------|-----------|
| **SpotTrading** | EKS (self-managed) | DynamoDB (orders) + Aurora PG (history) | ElastiCache Redis | SQS FIFO | Microsecond latency requires fine-grained node control; DynamoDB for sub-ms order state; FIFO guarantees ordering |
| **FuturesTrading** | EKS (self-managed) | Aurora PostgreSQL | ElastiCache Redis | SQS FIFO | Margin/position calculations require ACID; complex relational queries on positions |
| **Deposit** | ECS Fargate + Step Functions | Aurora PostgreSQL | — | SQS Standard | Workflow-oriented; Step Functions for approval chains; Fargate reduces ops overhead |
| **Withdrawal** | ECS Fargate + Step Functions | Aurora PostgreSQL | — | SQS Standard | Same rationale as Deposit; regulatory holds modeled as Step Functions wait states |
| **Identity** | Lambda + API Gateway | DynamoDB | ElastiCache Redis (session) | — | Auth is bursty; serverless scales to zero; Cognito handles OAuth2/OIDC |
| **MarketData** | ECS Fargate | DynamoDB (tick data) | ElastiCache Redis (live book) | MSK (Kafka) | High-throughput streaming; Kafka for guaranteed delivery from exchanges |
| **Notification** | Lambda | DynamoDB | — | SNS + SQS | Purely async, fan-out pattern; event-driven, zero sustained load |
| **RiskCompliance** | ECS Fargate | Aurora PostgreSQL | — | EventBridge | Consumes all domain events; relational DB for complex compliance queries |

### 3.3 Cross-Account Event Architecture

```
Event Flow Example: Trade Executed

spottrading-prod account
  EventBridge Bus: trading.spot.prod
       │
       ├─→ Rule: trade.executed → riskcompliance-prod bus (sync position risk)
       ├─→ Rule: order.filled → notification-prod bus (notify user)
       └─→ Rule: trade.settled → deposit-prod bus (update balance)

EventBridge Schema Registry (shared-services account)
  └── trading.spot.v1.TradeExecuted
  └── trading.futures.v1.PositionOpened
  └── finance.deposit.v1.DepositConfirmed
  └── identity.v1.UserKYCApproved
```

### 3.4 Security Architecture

```
Traffic Flow (Centralized Inspection Model):

INBOUND:
  Internet → Route53 → ALB (network-prod centralized ingress VPC)
           → AWS Network Firewall (inspect) → TGW → Domain VPC

OUTBOUND:
  Domain VPC → TGW → AWS Network Firewall (inspect) → NAT GW → Internet

INTER-ACCOUNT:
  Domain A VPC → TGW → Network Firewall (inspect East-West) → TGW → Domain B VPC

Security Services (mandatory in every account via SCP):
  ├── GuardDuty   → findings aggregated to security-prod via Organizations delegation
  ├── AWS Config  → compliance rules aggregated to security-prod
  ├── CloudTrail  → logs shipped to log-archive-prod S3 (cross-account)
  ├── VPC Flow Logs → log-archive-prod S3
  └── SecurityHub  → findings from all accounts to security-prod
```

### 3.5 Dev/Prod Isolation

**Network isolation:**
- Prod OU: Transit Gateway ID `tgw-prod-XXXXXXXX`
- Dev OU: Separate Transit Gateway ID `tgw-dev-YYYYYYYY`
- Zero routes exist between prod and dev TGWs (physically isolated)

**Policy isolation (SCPs):**
```json
// Attached to Production OU
{
  "Sid": "DenyDevVpcPeering",
  "Effect": "Deny",
  "Action": ["ec2:CreateVpcPeeringConnection", "ec2:AcceptVpcPeeringConnection"],
  "Resource": "*",
  "Condition": {
    "StringLike": { "ec2:RequesterVpc": "arn:aws:ec2:*:*:vpc/vpc-dev-*" }
  }
}
```

```json
// Attached to Development OU
{
  "Sid": "DenyProdAccountAccess",
  "Effect": "Deny",
  "Action": ["sts:AssumeRole"],
  "Resource": "arn:aws:iam::PROD_ACCOUNT_IDS:role/*"
}
```

---

## 4. Tag Policy Design

### 4.1 Tag Schema

| Tag Key | Required | Values | Purpose |
|---------|----------|--------|---------|
| `Company` | Yes | `CryptoTradingPlatform` | Top-level cost rollup |
| `Department` | Yes | `Trading` / `Finance` / `Platform` / `Security` / `Infrastructure` | Department cost rollup |
| `Service` | Yes | `SpotTrading` / `FuturesTrading` / `Deposit` / `Withdrawal` / `Identity` / `MarketData` / `Notification` / `RiskCompliance` | Service-level cost |
| `CostCenter` | Yes | `CC-TRD-SPOT` / `CC-TRD-FUT` / `CC-FIN-DEP` / `CC-FIN-WDR` / `CC-PLT-IDN` / `CC-PLT-MKT` / `CC-PLT-NOT` / `CC-PLT-RSK` | Finance system integration |
| `Environment` | Yes | `prod` / `dev` / `staging` | Env cost separation |
| `Owner` | Yes | team email (e.g., `trading-team@company.com`) | Accountability |
| `DataClassification` | Yes | `confidential` / `internal` / `public` | Compliance/security |
| `ManagedBy` | Yes | `terraform` / `manual` | IaC compliance |

### 4.2 Cost Hierarchy Reporting

```
AWS Cost Explorer → Cost Categories:

Level 1: Group by "Department" tag
  → Trading: $X,XXX/month
  → Finance:  $X,XXX/month
  → Platform: $X,XXX/month

Level 2: Filter Department=Trading, Group by "Service" tag
  → SpotTrading:    $X,XXX/month
  → FuturesTrading: $X,XXX/month

Level 3: Filter Service=SpotTrading, Group by resource type
  → EKS:       $XXX/month
  → DynamoDB:  $XXX/month
  → ElastiCache: $XX/month
```

### 4.3 Tag Enforcement Strategy

1. **AWS Tag Policies** (Organizations level) — define allowed key/value pairs, enforce on resource types
2. **AWS Config rule** `required-tags` — detect non-compliant resources, alert SecurityHub
3. **Terraform `required_tags` variable** in `account-factory` module — enforce at provisioning time
4. **SCP deny** — `Deny` on `ec2:RunInstances` when required tags are absent (optional, strictest mode)

---

## 5. Codebase Separation

### 5.1 Repository Structure

```
GitHub Organization: github.com/cryptotrading-platform
│
├── trading-platform-iac          # Infrastructure as Code
│   ├── org/                      # AWS Organizations, SCPs, Tag Policies
│   ├── accounts/                 # Per-account Terraform root modules
│   │   ├── prod/{domain}/        # Production account configs
│   │   └── dev/{domain}/         # Development account configs
│   ├── modules/                  # Reusable modules (Factory pattern)
│   │   ├── account-factory/      # THE factory module
│   │   ├── domain-vpc/
│   │   ├── eks-cluster/
│   │   ├── aurora-cluster/
│   │   ├── ecs-fargate/
│   │   ├── lambda-service/
│   │   └── security-baseline/
│   └── .github/workflows/        # Terraform plan (on PR), apply (on merge to main)
│
└── trading-platform-services     # Application Code
    ├── apps/                     # Frontend (Next.js, Turborepo)
    ├── services/                 # Backend microservices (per domain)
    │   ├── spot-trading/
    │   ├── futures-trading/
    │   ├── deposit/
    │   ├── withdrawal/
    │   ├── identity/
    │   ├── market-data/
    │   ├── notification/
    │   └── risk-compliance/
    ├── packages/                 # Shared: types, proto, event-schemas, api-client
    └── .github/workflows/        # Test, build Docker, push to ECR (shared-services account)
```

### 5.2 Separation Rationale

| Concern | IaC Repo | App Repo |
|---------|----------|----------|
| Release cadence | Planned events (weekly/monthly) | Multiple times per day |
| Reviewers | Platform/SRE team | Domain engineering teams |
| Blast radius | Can affect all environments | Scoped to one service |
| Credentials | Admin-level AWS access | ECR push, EKS deploy only |
| State management | Terraform state in S3 | Docker image tags in ECR |

---

## 6. Terraform Design Pattern: Factory

### 6.1 Decision

**Selected Pattern: Factory**

| Pattern | Assessment | Reason |
|---------|-----------|--------|
| Singleton | Partial use (TGW, S3 state bucket) | Too narrow — solves "one instance" not "many similar instances" |
| **Factory** | **Selected** | 8+ accounts with identical structure but different configs — factory produces them consistently from variable inputs |
| Composite | Used inside factory | Good for composing modules, but doesn't solve the "many accounts" problem alone |
| Prototype | Rejected | Terraform workspace cloning creates hidden state complexity at scale |
| Builder | Rejected | Step-by-step construction is already implicit in Terraform's dependency DAG |

### 6.2 Factory Pattern Concept

```
Variable Inputs          account-factory module         Account "Product"
─────────────────        ──────────────────────         ─────────────────
domain = "spottrading"                                  VPC 10.2.0.0/16
department = "Trading"   ┌── domain-vpc ──────────→    Subnets (3 AZs)
environment = "prod"     ├── network-firewall ──→       AWS Network Firewall
vpc_cidr = "10.2.0.0/16" ├── security-baseline ──→     GuardDuty enabled
cost_center = "CC-TRD-SPOT" ├── eventbridge-bus ──→    EventBridge custom bus
tags = { ... }           ├── cloudtrail ─────────→     CloudTrail → log-archive
                         └── tgw-attachment ─────→     TGW attachment + routes
```

### 6.3 Factory Guarantees

Every account produced by the factory ALWAYS has:
- [ ] Exactly 1 VPC with standard subnet layout (public / private / firewall / db)
- [ ] AWS Network Firewall in dedicated firewall subnets
- [ ] GuardDuty detector enabled (findings → security-prod)
- [ ] CloudTrail (multi-region, log file validation) → log-archive-prod S3
- [ ] VPC Flow Logs → log-archive-prod S3
- [ ] EventBridge custom bus for domain events
- [ ] AWS Config recorder
- [ ] All 8 required tags applied to every resource
- [ ] TGW attachment to the correct route table (prod vs dev isolation)

### 6.4 State Management

```
Terraform State (Remote, per account):
  S3 Bucket: tf-state-trading-platform-{account-id}
  Key:       {environment}/{domain}/terraform.tfstate
  Locking:   DynamoDB table tf-state-locks-{account-id}
  Encryption: KMS key (dedicated per account)

State isolation: Each domain account has its own S3 bucket for state
→ A failed apply in spottrading cannot corrupt futurestrading state
```

---

## 7. Risks

| ID | Risk | Likelihood | Impact | Mitigation |
|----|------|-----------|--------|------------|
| R-01 | Account vending (creating 16+ accounts) is slow | Medium | Medium | Use AWS Control Tower with Account Factory for Terraform (AFT) |
| R-02 | EventBridge cross-account event schema drift | High | High | EventBridge Schema Registry with schema validation enforced in CI |
| R-03 | Tag policy compliance rate low at start | High | Medium | Config rule + weekly tagging compliance report to team leads |
| R-04 | Network Firewall adds latency to inter-account calls | Medium | Medium | Baseline latency testing; async event-driven patterns for most calls |
| R-05 | Terraform state corruption during factory refactoring | Low | High | State file per account, never share state; `terraform state mv` for refactors |
| R-06 | Dev engineer accidentally targets prod account | Medium | High | SCPs deny cross-env actions; separate AWS SSO permission sets per OU |

---

## 8. Success Metrics

| Metric | Target |
|--------|--------|
| All accounts provisioned with zero manual security steps | 100% |
| Tag compliance rate across all resources | ≥ 98% |
| Cost visibility by department in AWS Cost Explorer | Department + Service + Resource granularity |
| Dev → Prod network path exists | 0 routes (verified by network reachability test) |
| Security findings aggregated to security-prod | 100% of accounts |
| Terraform plan runs with no diff after stable provisioning | Pass |

---

## 9. Implementation Phases

| Phase | Scope | Deliverable |
|-------|-------|-------------|
| **Phase 1** | AWS Organizations, OUs, SCPs, Tag Policies | org/ Terraform module |
| **Phase 2** | Network account (TGW prod + dev, centralized egress) | network-prod account |
| **Phase 3** | Security account + log-archive account | security-prod, log-archive-prod |
| **Phase 4** | account-factory module (core) | modules/account-factory/ |
| **Phase 5** | Identity + MarketData accounts (simpler, validate factory) | identity-prod/dev, marketdata-prod/dev |
| **Phase 6** | Trading accounts (SpotTrading, FuturesTrading) | spottrading-prod/dev, futurestrading-prod/dev |
| **Phase 7** | Finance accounts (Deposit, Withdrawal) | deposit-prod/dev, withdrawal-prod/dev |
| **Phase 8** | Platform accounts (Notification, RiskCompliance) | notification-prod/dev, riskcompliance-prod/dev |
| **Phase 9** | EventBridge cross-account routing wiring | All event rules + schema registry |

---

## 10. Next Steps

- [ ] Review and approve this Plan document
- [ ] Run `/pdca design trading-platform` to create detailed technical Design document
- [ ] Define Terraform module interfaces (variable contracts per module)
- [ ] Select AWS region (recommend `ap-northeast-2` based on CLAUDE.md existing setup)
- [ ] Confirm AWS account IDs for existing accounts (or plan new account creation via Control Tower)
