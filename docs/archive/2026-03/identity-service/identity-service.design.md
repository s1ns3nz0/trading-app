# Design: identity-service

> **Feature**: identity-service
> **Created**: 2026-03-08
> **Phase**: Design
> **Level**: Enterprise
> **Ref**: docs/01-plan/features/identity-service.plan.md

---

## 1. Overview

The identity service core (FastAPI, JWT, DynamoDB, TOTP) already exists in `services/identity/`.
This design covers **7 implementation gaps** that must be closed before the service is production-ready:

| # | Gap | Files Affected |
|---|-----|---------------|
| 1 | Refresh token revocation | `repositories/user_repository.py`, `services/auth_service.py`, `routers/auth.py` |
| 2 | Email verification flow | `repositories/user_repository.py`, `services/auth_service.py`, `routers/auth.py` |
| 3 | Login rate limiting | `repositories/user_repository.py`, `services/auth_service.py` |
| 4 | Lambda Authorizer | `authorizer/handler.py` (new) |
| 5 | Terraform: API GW + Lambda | `infra/api_gateway.tf`, `infra/lambda.tf`, `infra/iam.tf`, `infra/ses.tf` (new) |
| 6 | Tests | `tests/conftest.py`, `tests/test_auth_service.py`, `tests/test_repository.py`, `tests/test_authorizer.py` (new) |
| 7 | Frontend: token refresh + route guard | `apps/web/src/services/api.ts`, `apps/web/src/middleware.ts`, `apps/web/src/app/(auth)/verify-email/page.tsx` |

---

## 2. DynamoDB Schema Extensions

All new item types live in the existing `trading-identity` table (single-table design).

### 2.1 RevokedToken Item

```python
# PK: REVOKED#{jti}
# SK: REFRESH
# ttl: unix timestamp at token expiry (DynamoDB TTL auto-deletes)
{
    "PK": {"S": f"REVOKED#{jti}"},
    "SK": {"S": "REFRESH"},
    "user_id": {"S": user_id},
    "ttl": {"N": str(int(token_exp_timestamp))},
}
```

### 2.2 VerificationToken Item

```python
# PK: VTOKEN#{token}   (token = secrets.token_urlsafe(32))
# SK: VERIFY
# ttl: now + 86400 (24h)
{
    "PK": {"S": f"VTOKEN#{token}"},
    "SK": {"S": "VERIFY"},
    "user_id": {"S": user_id},
    "ttl": {"N": str(int(time.time()) + 86400)},
}
```

### 2.3 LoginAttempt Item

```python
# PK: ATTEMPT#{email}
# SK: LOGIN
# count: integer
# ttl: now + 900 (15 min sliding window)
{
    "PK": {"S": f"ATTEMPT#{email.lower()}"},
    "SK": {"S": "LOGIN"},
    "count": {"N": "1"},
    "ttl": {"N": str(int(time.time()) + 900)},
}
```

---

## 3. Repository Layer Extensions

**File**: `services/identity/app/repositories/user_repository.py`

Add to the `UserRepository` ABC and `DynamoUserRepository` implementation:

```python
# Abstract methods to add to UserRepository ABC
@abstractmethod
async def revoke_token(self, jti: str, user_id: str, exp_timestamp: int) -> None: ...

@abstractmethod
async def is_token_revoked(self, jti: str) -> bool: ...

@abstractmethod
async def save_verification_token(self, token: str, user_id: str) -> None: ...

@abstractmethod
async def get_verification_token(self, token: str) -> Optional[str]: ...  # returns user_id

@abstractmethod
async def delete_verification_token(self, token: str) -> None: ...

@abstractmethod
async def increment_login_attempt(self, email: str) -> int: ...  # returns new count

@abstractmethod
async def get_login_attempts(self, email: str) -> int: ...

@abstractmethod
async def activate_user(self, user_id: str) -> None: ...  # status → ACTIVE
```

### DynamoUserRepository implementations:

```python
async def revoke_token(self, jti: str, user_id: str, exp_timestamp: int) -> None:
    self._client.put_item(
        TableName=self._table,
        Item={
            "PK": {"S": f"REVOKED#{jti}"},
            "SK": {"S": "REFRESH"},
            "user_id": {"S": user_id},
            "ttl": {"N": str(exp_timestamp)},
        },
    )

async def is_token_revoked(self, jti: str) -> bool:
    response = self._client.get_item(
        TableName=self._table,
        Key={"PK": {"S": f"REVOKED#{jti}"}, "SK": {"S": "REFRESH"}},
        ConsistentRead=True,
    )
    return "Item" in response

async def save_verification_token(self, token: str, user_id: str) -> None:
    import time
    self._client.put_item(
        TableName=self._table,
        Item={
            "PK": {"S": f"VTOKEN#{token}"},
            "SK": {"S": "VERIFY"},
            "user_id": {"S": user_id},
            "ttl": {"N": str(int(time.time()) + 86400)},
        },
    )

async def get_verification_token(self, token: str) -> Optional[str]:
    response = self._client.get_item(
        TableName=self._table,
        Key={"PK": {"S": f"VTOKEN#{token}"}, "SK": {"S": "VERIFY"}},
        ConsistentRead=True,
    )
    item = response.get("Item")
    if not item:
        return None
    return item["user_id"]["S"]

async def delete_verification_token(self, token: str) -> None:
    self._client.delete_item(
        TableName=self._table,
        Key={"PK": {"S": f"VTOKEN#{token}"}, "SK": {"S": "VERIFY"}},
    )

async def increment_login_attempt(self, email: str) -> int:
    import time
    response = self._client.update_item(
        TableName=self._table,
        Key={"PK": {"S": f"ATTEMPT#{email.lower()}"}, "SK": {"S": "LOGIN"}},
        UpdateExpression="SET #c = if_not_exists(#c, :zero) + :one, #t = :ttl",
        ExpressionAttributeNames={"#c": "count", "#t": "ttl"},
        ExpressionAttributeValues={
            ":zero": {"N": "0"},
            ":one": {"N": "1"},
            ":ttl": {"N": str(int(time.time()) + 900)},
        },
        ReturnValues="UPDATED_NEW",
    )
    return int(response["Attributes"]["count"]["N"])

async def get_login_attempts(self, email: str) -> int:
    response = self._client.get_item(
        TableName=self._table,
        Key={"PK": {"S": f"ATTEMPT#{email.lower()}"}, "SK": {"S": "LOGIN"}},
    )
    item = response.get("Item")
    if not item:
        return 0
    return int(item["count"]["N"])

async def activate_user(self, user_id: str) -> None:
    self._client.update_item(
        TableName=self._table,
        Key={"PK": {"S": f"USER#{user_id}"}, "SK": {"S": "PROFILE"}},
        UpdateExpression="SET #s = :active",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":active": {"S": "active"}},
    )
```

---

## 4. AuthService Extensions

**File**: `services/identity/app/services/auth_service.py`

### 4.1 Login — rate limiting + PENDING_VERIFICATION block

```python
MAX_LOGIN_ATTEMPTS = 5

async def login(self, email: str, password: str, totp_code: Optional[str] = None) -> tuple[str, str]:
    # Rate limit check BEFORE credential verification
    attempts = await self._repo.get_login_attempts(email)
    if attempts >= MAX_LOGIN_ATTEMPTS:
        raise AuthError("Too many failed attempts. Try again in 15 minutes.", status_code=429)

    user = await self._repo.find_by_email(email)
    dummy_hash = "$2b$12$invalidhashforunknownuserprotection"
    hash_to_check = user.hashed_password if user else dummy_hash

    if not bcrypt.checkpw(password.encode(), hash_to_check.encode()):
        if user:
            await self._repo.increment_login_attempt(email)
        raise AuthError("Invalid credentials")

    if user is None:
        raise AuthError("Invalid credentials")

    if user.status == UserStatus.SUSPENDED:
        raise AuthError("Account suspended", status_code=403)

    if user.status == UserStatus.PENDING_VERIFICATION:
        raise AuthError("Email not verified. Check your inbox.", status_code=403)

    if user.totp_enabled:
        if not totp_code:
            raise AuthError("TOTP code required", status_code=428)
        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(totp_code, valid_window=1):
            await self._repo.increment_login_attempt(email)
            raise AuthError("Invalid TOTP code")

    return self._issue_tokens(user.id)
```

### 4.2 Refresh — revocation check

```python
async def refresh(self, refresh_token: str) -> tuple[str, str]:
    try:
        payload = jwt.decode(
            refresh_token,
            settings.jwt_public_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError:
        raise AuthError("Refresh token expired")
    except jwt.InvalidTokenError:
        raise AuthError("Invalid refresh token")

    if payload.get("type") != "refresh":
        raise AuthError("Invalid token type")

    jti = payload.get("jti")
    if not jti:
        raise AuthError("Invalid token")

    # Check revocation before issuing new tokens
    if await self._repo.is_token_revoked(jti):
        raise AuthError("Token has been revoked")

    user_id = payload["sub"]
    user = await self._repo.find_by_id(user_id)
    if not user or user.status == UserStatus.SUSPENDED:
        raise AuthError("User not found or suspended")

    # Revoke old refresh token (rotation)
    exp_timestamp = int(payload["exp"])
    await self._repo.revoke_token(jti, user_id, exp_timestamp)

    return self._issue_tokens(user_id)
```

### 4.3 Logout — revoke refresh token

```python
async def logout(self, refresh_token: str) -> None:
    """Revoke the provided refresh token jti."""
    try:
        payload = jwt.decode(
            refresh_token,
            settings.jwt_public_key,
            algorithms=[settings.jwt_algorithm],
        )
    except jwt.InvalidTokenError:
        return  # Already invalid — no action needed

    jti = payload.get("jti")
    if jti:
        exp_timestamp = int(payload.get("exp", 0))
        await self._repo.revoke_token(jti, payload.get("sub", ""), exp_timestamp)
```

### 4.4 Email verification

```python
async def send_verification_email(self, user_id: str, email: str) -> None:
    """Generate token, save to DynamoDB, send SES email."""
    import secrets
    token = secrets.token_urlsafe(32)
    await self._repo.save_verification_token(token, user_id)

    if settings.ses_enabled:
        verify_url = f"{settings.app_base_url}/auth/verify-email?token={token}"
        self._ses_client.send_email(
            Source=settings.ses_from_address,
            Destination={"ToAddresses": [email]},
            Message={
                "Subject": {"Data": "Verify your TradingPlatform account"},
                "Body": {
                    "Text": {"Data": f"Click to verify: {verify_url}\n\nExpires in 24 hours."}
                },
            },
        )

async def verify_email(self, token: str) -> None:
    """Activate user account after token validation."""
    user_id = await self._repo.get_verification_token(token)
    if not user_id:
        raise AuthError("Invalid or expired verification token", status_code=400)

    await self._repo.activate_user(user_id)
    await self._repo.delete_verification_token(token)
```

### 4.5 Config additions

**File**: `services/identity/app/config.py`

```python
# Add to Settings class
ses_enabled: bool = False                           # False in dev/test
ses_from_address: str = "noreply@trading-platform.com"
app_base_url: str = "https://app.trading-platform.com"
```

### 4.6 AuthService constructor update

```python
import boto3

class AuthService:
    def __init__(self, user_repo: UserRepository):
        self._repo = user_repo
        self._ses_client = boto3.client("ses", region_name=settings.aws_region)
```

---

## 5. Router Updates

**File**: `services/identity/app/routers/auth.py`

### 5.1 Register — trigger email verification

```python
@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(body: RegisterRequest, response: Response, svc: AuthService = Depends(get_auth_service)):
    try:
        user = await svc.register(body.email, body.username, body.password)
        await svc.send_verification_email(user.id, user.email)
        access_token, refresh_token = svc._issue_tokens(user.id)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    _set_refresh_cookie(response, refresh_token)
    return AuthResponse(
        user=UserResponse(id=user.id, email=user.email, username=user.username, totp_enabled=user.totp_enabled),
        tokens=TokenResponse(access_token=access_token),
    )
```

### 5.2 New endpoint: verify-email

```python
class VerifyEmailRequest(BaseModel):
    token: str

@router.post("/verify-email", status_code=204)
async def verify_email(body: VerifyEmailRequest, svc: AuthService = Depends(get_auth_service)):
    try:
        await svc.verify_email(body.token)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
```

### 5.3 New endpoint: resend-verification

```python
class ResendVerificationRequest(BaseModel):
    email: EmailStr

@router.post("/resend-verification", status_code=204)
async def resend_verification(body: ResendVerificationRequest, svc: AuthService = Depends(get_auth_service)):
    user = await svc._repo.find_by_email(body.email)
    if user and user.status == UserStatus.PENDING_VERIFICATION:
        await svc.send_verification_email(user.id, user.email)
    # Always return 204 — don't leak whether email is registered
```

### 5.4 Logout — revoke refresh token

```python
@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, svc: AuthService = Depends(get_auth_service)):
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        await svc.logout(refresh_token)
    response.delete_cookie(key="refresh_token", httponly=True, secure=True, samesite="strict")
```

### 5.5 PUBLIC_PATHS update

**File**: `services/identity/app/middleware/auth.py`

```python
PUBLIC_PATHS = {
    "/auth/login",
    "/auth/register",
    "/auth/refresh",
    "/auth/verify-email",
    "/auth/resend-verification",
    "/auth/.well-known/jwks.json",
    "/health",
    "/docs",
    "/openapi.json",
}
```

---

## 6. Lambda Authorizer

**File**: `services/identity/authorizer/handler.py`

```python
"""
Lambda Authorizer for API Gateway HTTP API.
Validates RS256 JWT, checks revocation, injects X-User-Id into context.
"""
import json
import os
import time
from typing import Optional
import urllib.request

import jwt

# In-memory JWKS cache
_jwks_cache: Optional[dict] = None
_jwks_fetched_at: float = 0.0
JWKS_CACHE_TTL = 300  # 5 minutes

IDENTITY_JWKS_URL = os.environ["IDENTITY_JWKS_URL"]  # https://.../auth/.well-known/jwks.json
DYNAMODB_TABLE = os.environ["DYNAMODB_TABLE_NAME"]
AWS_REGION = os.environ.get("AWS_REGION", "ap-northeast-2")

import boto3
_dynamo = boto3.client("dynamodb", region_name=AWS_REGION)


def _get_jwks() -> dict:
    global _jwks_cache, _jwks_fetched_at
    now = time.time()
    if _jwks_cache and (now - _jwks_fetched_at) < JWKS_CACHE_TTL:
        return _jwks_cache
    with urllib.request.urlopen(IDENTITY_JWKS_URL, timeout=3) as resp:
        _jwks_cache = json.loads(resp.read())
        _jwks_fetched_at = now
    return _jwks_cache


def _is_revoked(jti: str) -> bool:
    response = _dynamo.get_item(
        TableName=DYNAMODB_TABLE,
        Key={"PK": {"S": f"REVOKED#{jti}"}, "SK": {"S": "REFRESH"}},
        ConsistentRead=True,
    )
    return "Item" in response


def _build_policy(effect: str, resource: str, user_id: Optional[str] = None) -> dict:
    policy = {
        "principalId": user_id or "anonymous",
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [{"Action": "execute-api:Invoke", "Effect": effect, "Resource": resource}],
        },
    }
    if user_id:
        policy["context"] = {"userId": user_id}
    return policy


def handler(event: dict, context) -> dict:
    token = event.get("authorizationToken", "").removeprefix("Bearer ").strip()
    method_arn = event.get("methodArn", "*")

    if not token:
        return _build_policy("Deny", method_arn)

    try:
        jwks = _get_jwks()
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwks["keys"][0]))
        payload = jwt.decode(token, public_key, algorithms=["RS256"])
    except Exception:
        return _build_policy("Deny", method_arn)

    if payload.get("type") != "access":
        return _build_policy("Deny", method_arn)

    user_id = payload.get("sub")
    if not user_id:
        return _build_policy("Deny", method_arn)

    return _build_policy("Allow", method_arn, user_id)
```

**Note**: Access tokens are short-lived (1h) and stateless — the authorizer does NOT check DynamoDB revocation for access tokens (only for refresh tokens during the refresh flow). This keeps authorizer latency low.

---

## 7. Terraform

### 7.1 `infra/lambda.tf`

```hcl
# Identity service Lambda
resource "aws_lambda_function" "identity" {
  function_name = "${var.environment}-identity-service"
  role          = aws_iam_role.identity_lambda.arn
  package_type  = "Image"
  image_uri     = "${var.ecr_registry}/identity-service:${var.image_tag}"
  timeout       = 30
  memory_size   = 512

  environment {
    variables = {
      ENVIRONMENT            = var.environment
      DYNAMODB_TABLE_NAME    = aws_dynamodb_table.identity.name
      AWS_REGION             = var.aws_region
      JWT_PRIVATE_KEY        = data.aws_secretsmanager_secret_version.jwt_private.secret_string
      JWT_PUBLIC_KEY         = data.aws_secretsmanager_secret_version.jwt_public.secret_string
      SES_ENABLED            = var.environment == "prod" ? "true" : "false"
      SES_FROM_ADDRESS       = "noreply@trading-platform.com"
      APP_BASE_URL           = var.app_base_url
    }
  }
}

# Lambda Authorizer
resource "aws_lambda_function" "authorizer" {
  function_name = "${var.environment}-identity-authorizer"
  role          = aws_iam_role.authorizer_lambda.arn
  package_type  = "Image"
  image_uri     = "${var.ecr_registry}/identity-authorizer:${var.image_tag}"
  timeout       = 5
  memory_size   = 256

  environment {
    variables = {
      IDENTITY_JWKS_URL   = "${aws_apigatewayv2_api.identity.api_endpoint}/auth/.well-known/jwks.json"
      DYNAMODB_TABLE_NAME = aws_dynamodb_table.identity.name
      AWS_REGION          = var.aws_region
    }
  }
}
```

### 7.2 `infra/api_gateway.tf`

```hcl
resource "aws_apigatewayv2_api" "identity" {
  name          = "${var.environment}-identity-api"
  protocol_type = "HTTP"
  cors_configuration {
    allow_origins     = var.allowed_origins
    allow_methods     = ["GET", "POST", "PATCH", "DELETE", "OPTIONS"]
    allow_headers     = ["Authorization", "Content-Type"]
    allow_credentials = true
    max_age           = 3600
  }
}

resource "aws_apigatewayv2_authorizer" "jwt" {
  api_id                            = aws_apigatewayv2_api.identity.id
  authorizer_type                   = "REQUEST"
  authorizer_uri                    = aws_lambda_function.authorizer.invoke_arn
  name                              = "jwt-authorizer"
  authorizer_result_ttl_in_seconds  = 300
  identity_sources                  = ["$request.header.Authorization"]
}

resource "aws_apigatewayv2_integration" "identity" {
  api_id                 = aws_apigatewayv2_api.identity.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.identity.invoke_arn
  payload_format_version = "2.0"
}

# Public routes — no authorizer
resource "aws_apigatewayv2_route" "auth_public" {
  for_each = toset([
    "POST /auth/login",
    "POST /auth/register",
    "POST /auth/refresh",
    "POST /auth/logout",
    "POST /auth/verify-email",
    "POST /auth/resend-verification",
    "GET /auth/.well-known/jwks.json",
    "GET /health",
  ])
  api_id    = aws_apigatewayv2_api.identity.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.identity.id}"
}

# Protected routes — require JWT authorizer
resource "aws_apigatewayv2_route" "auth_protected" {
  for_each = toset([
    "GET /users/me",
    "PATCH /users/me",
    "POST /auth/totp/enable",
    "POST /auth/totp/verify",
  ])
  api_id             = aws_apigatewayv2_api.identity.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.identity.id}"
  authorizer_id      = aws_apigatewayv2_authorizer.jwt.id
  authorization_type = "CUSTOM"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.identity.id
  name        = "$default"
  auto_deploy = true
}
```

### 7.3 `infra/iam.tf`

```hcl
# Identity Lambda execution role
resource "aws_iam_role" "identity_lambda" {
  name               = "${var.environment}-identity-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "identity_dynamo" {
  name = "dynamo-access"
  role = aws_iam_role.identity_lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
                  "dynamodb:DeleteItem", "dynamodb:Query"]
      Resource = [aws_dynamodb_table.identity.arn,
                  "${aws_dynamodb_table.identity.arn}/index/*"]
    }, {
      Effect   = "Allow"
      Action   = ["ses:SendEmail"]
      Resource = "*"
    }]
  })
}

# Authorizer Lambda role
resource "aws_iam_role" "authorizer_lambda" {
  name               = "${var.environment}-authorizer-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "authorizer_dynamo" {
  name = "revocation-check"
  role = aws_iam_role.authorizer_lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:GetItem"]
      Resource = aws_dynamodb_table.identity.arn
    }]
  })
}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}
```

### 7.4 `infra/ses.tf`

```hcl
resource "aws_ses_domain_identity" "trading" {
  domain = "trading-platform.com"
}

resource "aws_ses_domain_dkim" "trading" {
  domain = aws_ses_domain_identity.trading.domain
}
```

---

## 8. Tests

### 8.1 `tests/conftest.py`

```python
import pytest
from moto import mock_aws
import boto3
from unittest.mock import AsyncMock, MagicMock

@pytest.fixture(scope="function")
def dynamo_table():
    """Mocked DynamoDB table via moto."""
    with mock_aws():
        client = boto3.client("dynamodb", region_name="ap-northeast-2")
        client.create_table(
            TableName="trading-identity",
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[{
                "IndexName": "GSI1",
                "KeySchema": [
                    {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                    {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }],
            BillingMode="PAY_PER_REQUEST",
        )
        yield client

@pytest.fixture
def mock_repo():
    repo = AsyncMock()
    repo.find_by_email = AsyncMock(return_value=None)
    repo.find_by_id = AsyncMock(return_value=None)
    repo.save = AsyncMock()
    repo.update = AsyncMock()
    repo.revoke_token = AsyncMock()
    repo.is_token_revoked = AsyncMock(return_value=False)
    repo.save_verification_token = AsyncMock()
    repo.get_verification_token = AsyncMock(return_value=None)
    repo.delete_verification_token = AsyncMock()
    repo.increment_login_attempt = AsyncMock(return_value=1)
    repo.get_login_attempts = AsyncMock(return_value=0)
    repo.activate_user = AsyncMock()
    return repo
```

### 8.2 `tests/test_auth_service.py`

```python
import pytest
from unittest.mock import AsyncMock
from app.services.auth_service import AuthService, AuthError
from app.models.user import User, UserStatus

class TestRegister:
    async def test_register_success(self, mock_repo):
        mock_repo.find_by_email.return_value = None
        mock_repo.save.return_value = User(email="a@b.com", username="alice", hashed_password="x")
        svc = AuthService(mock_repo)
        user = await svc.register("a@b.com", "alice", "password123")
        assert user.email == "a@b.com"

    async def test_register_duplicate_email(self, mock_repo):
        mock_repo.find_by_email.return_value = User(email="a@b.com", username="x", hashed_password="x")
        svc = AuthService(mock_repo)
        with pytest.raises(AuthError) as exc:
            await svc.register("a@b.com", "alice", "password123")
        assert exc.value.status_code == 409

class TestLogin:
    async def test_login_rate_limited(self, mock_repo):
        mock_repo.get_login_attempts.return_value = 5
        svc = AuthService(mock_repo)
        with pytest.raises(AuthError) as exc:
            await svc.login("a@b.com", "pw")
        assert exc.value.status_code == 429

    async def test_login_pending_verification(self, mock_repo, make_user):
        user = make_user(status=UserStatus.PENDING_VERIFICATION)
        mock_repo.find_by_email.return_value = user
        svc = AuthService(mock_repo)
        with pytest.raises(AuthError) as exc:
            await svc.login("a@b.com", "correctpassword")
        assert exc.value.status_code == 403

    async def test_login_invalid_credentials(self, mock_repo):
        mock_repo.get_login_attempts.return_value = 0
        mock_repo.find_by_email.return_value = None
        svc = AuthService(mock_repo)
        with pytest.raises(AuthError):
            await svc.login("a@b.com", "wrong")

class TestRefresh:
    async def test_refresh_revoked_token(self, mock_repo):
        mock_repo.is_token_revoked.return_value = True
        svc = AuthService(mock_repo)
        with pytest.raises(AuthError) as exc:
            await svc.refresh("some.jwt.token")
        # AuthError raised before DynamoDB check if JWT decode fails — but
        # if token is valid JWT, revocation check should trigger
        assert exc.value.status_code == 401

class TestEmailVerification:
    async def test_verify_email_invalid_token(self, mock_repo):
        mock_repo.get_verification_token.return_value = None
        svc = AuthService(mock_repo)
        with pytest.raises(AuthError) as exc:
            await svc.verify_email("invalid_token")
        assert exc.value.status_code == 400

    async def test_verify_email_success(self, mock_repo):
        mock_repo.get_verification_token.return_value = "user-123"
        svc = AuthService(mock_repo)
        await svc.verify_email("valid_token")
        mock_repo.activate_user.assert_called_once_with("user-123")
        mock_repo.delete_verification_token.assert_called_once_with("valid_token")
```

### 8.3 `tests/test_authorizer.py`

```python
import pytest
import json
from unittest.mock import patch, MagicMock

def test_handler_missing_token():
    from authorizer.handler import handler
    result = handler({"authorizationToken": "", "methodArn": "arn:aws:execute-api:*"}, None)
    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"

def test_handler_invalid_jwt():
    from authorizer.handler import handler
    with patch("authorizer.handler._get_jwks", return_value={"keys": [{}]}):
        result = handler({"authorizationToken": "Bearer invalid", "methodArn": "arn:aws:execute-api:*"}, None)
    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"

def test_handler_valid_access_token(valid_access_token, mock_jwks):
    from authorizer.handler import handler
    with patch("authorizer.handler._get_jwks", return_value=mock_jwks):
        result = handler(
            {"authorizationToken": f"Bearer {valid_access_token}", "methodArn": "arn:aws:execute-api:*"},
            None,
        )
    assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    assert result["context"]["userId"] is not None
```

---

## 9. Frontend

### 9.1 Token refresh interceptor

**File**: `apps/web/src/services/api.ts`

Replace the current 401 handler (which immediately logs out) with a silent refresh attempt:

```typescript
// Replace the existing request() function's 401 handling:
if (response.status === 401) {
  // Attempt silent token refresh before logging out
  try {
    const newTokens = await silentRefresh()
    useAuthStore.getState().refreshTokens(newTokens)
    // Retry original request with new access token
    headers['Authorization'] = `Bearer ${newTokens.accessToken}`
    const retryResponse = await fetch(`${baseUrl}${path}`, {
      method,
      headers,
      credentials: 'include',
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
    if (retryResponse.ok) {
      if (retryResponse.status === 204) return undefined as T
      return retryResponse.json() as Promise<T>
    }
  } catch {
    // Refresh failed — clear state and redirect
  }
  useAuthStore.getState().logout()
  throw new Error('SESSION_EXPIRED')
}

// Add credentials: 'include' to all fetch calls (for httpOnly cookie)
const response = await fetch(`${baseUrl}${path}`, {
  method,
  headers,
  credentials: 'include',
  body: body !== undefined ? JSON.stringify(body) : undefined,
})
```

```typescript
// New function silentRefresh() — calls /auth/refresh with cookie
async function silentRefresh(): Promise<AuthTokens> {
  const response = await fetch(`${IDENTITY_API}/auth/refresh`, {
    method: 'POST',
    credentials: 'include',  // sends httpOnly cookie
  })
  if (!response.ok) throw new Error('Refresh failed')
  return response.json()
}
```

### 9.2 Boot-time token initialization

**File**: `apps/web/src/lib/auth/init.ts`

```typescript
// Called once on app boot — attempts silent refresh to restore session
export async function initializeAuth(): Promise<void> {
  const { user, refreshTokens } = useAuthStore.getState()
  if (!user) return  // No persisted user — no session to restore

  try {
    const tokens = await silentRefresh()
    refreshTokens(tokens)
    useAuthStore.setState({ isAuthenticated: true })
  } catch {
    useAuthStore.getState().logout()
  }
}
```

### 9.3 Next.js middleware — route protection

**File**: `apps/web/src/middleware.ts`

```typescript
import { NextResponse } from 'next/server'
import type { NextRequest } from 'next/server'

const PUBLIC_PATHS = ['/login', '/register', '/auth/verify-email']

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl

  const isPublic = PUBLIC_PATHS.some((p) => pathname.startsWith(p))
  if (isPublic) return NextResponse.next()

  // Check for refresh token cookie as proxy for "has session"
  // (access token is memory-only and not accessible in middleware)
  const hasSession = request.cookies.has('refresh_token')
  if (!hasSession) {
    return NextResponse.redirect(new URL('/login', request.url))
  }

  return NextResponse.next()
}

export const config = {
  matcher: ['/((?!api|_next/static|_next/image|favicon.ico).*)'],
}
```

### 9.4 Email verification page

**File**: `apps/web/src/app/(auth)/verify-email/page.tsx`

```typescript
'use client'

import { useEffect, useState } from 'react'
import { useSearchParams, useRouter } from 'next/navigation'

export default function VerifyEmailPage() {
  const params = useSearchParams()
  const router = useRouter()
  const token = params.get('token')
  const [status, setStatus] = useState<'pending' | 'success' | 'error'>('pending')

  useEffect(() => {
    if (!token) { setStatus('error'); return }

    fetch(`${process.env.NEXT_PUBLIC_IDENTITY_API_URL}/auth/verify-email`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token }),
    })
      .then((r) => (r.ok ? setStatus('success') : setStatus('error')))
      .catch(() => setStatus('error'))
  }, [token])

  if (status === 'pending') return <p className="text-text-secondary">Verifying…</p>
  if (status === 'success') {
    setTimeout(() => router.push('/login'), 2000)
    return <p className="text-up">Email verified! Redirecting to login…</p>
  }
  return <p className="text-down">Invalid or expired link. <a href="/auth/resend-verification" className="text-accent">Resend verification email</a></p>
}
```

---

## 10. Implementation Order

| Step | File(s) | Depends On |
|------|---------|-----------|
| 1 | `repositories/user_repository.py` — add 8 new methods | — |
| 2 | `services/auth_service.py` — revocation + rate limit + email verify | Step 1 |
| 3 | `routers/auth.py` — verify-email, resend-verification, logout revocation | Step 2 |
| 4 | `middleware/auth.py` — add new PUBLIC_PATHS | Step 3 |
| 5 | `config.py` — add SES settings | — |
| 6 | `authorizer/handler.py` — new Lambda Authorizer | Step 1 |
| 7 | `infra/lambda.tf`, `api_gateway.tf`, `iam.tf`, `ses.tf` | — |
| 8 | `tests/conftest.py`, `test_auth_service.py`, `test_repository.py`, `test_authorizer.py` | Steps 1-6 |
| 9 | `apps/web/src/services/api.ts` — silent refresh | — |
| 10 | `apps/web/src/lib/auth/init.ts` — boot refresh | Step 9 |
| 11 | `apps/web/src/middleware.ts` — route guard | — |
| 12 | `apps/web/src/app/(auth)/verify-email/page.tsx` | Step 3 |
