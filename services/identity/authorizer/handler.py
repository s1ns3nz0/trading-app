"""
Lambda Authorizer for API Gateway HTTP API.

Validates RS256 JWT access tokens, injects X-User-Id into request context.
JWKS is cached in-memory for 5 minutes to avoid calling identity service on every request.
Access tokens are NOT checked against DynamoDB revocation (short-lived, stateless).
"""

import json
import os
import time
from typing import Optional
import urllib.request

import boto3
import jwt

# ──────────────────────────────────────────────
# Configuration from Lambda environment
# ──────────────────────────────────────────────

IDENTITY_JWKS_URL: str = os.environ["IDENTITY_JWKS_URL"]
DYNAMODB_TABLE: str = os.environ["DYNAMODB_TABLE_NAME"]
AWS_REGION: str = os.environ.get("AWS_REGION", "ap-northeast-2")
JWKS_CACHE_TTL: int = 300  # 5 minutes

# ──────────────────────────────────────────────
# Module-level singletons (persist across warm invocations)
# ──────────────────────────────────────────────

_jwks_cache: Optional[dict] = None
_jwks_fetched_at: float = 0.0
_dynamo = boto3.client("dynamodb", region_name=AWS_REGION)


def _get_jwks() -> dict:
    """Fetch JWKS from identity service with in-memory TTL cache."""
    global _jwks_cache, _jwks_fetched_at
    now = time.time()
    if _jwks_cache and (now - _jwks_fetched_at) < JWKS_CACHE_TTL:
        return _jwks_cache
    with urllib.request.urlopen(IDENTITY_JWKS_URL, timeout=3) as resp:
        _jwks_cache = json.loads(resp.read())
        _jwks_fetched_at = now
    return _jwks_cache


def _build_policy(effect: str, resource: str, user_id: Optional[str] = None) -> dict:
    """Build IAM policy document for API Gateway authorizer response."""
    policy: dict = {
        "principalId": user_id or "anonymous",
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": resource,
                }
            ],
        },
    }
    if user_id:
        policy["context"] = {"userId": user_id}
    return policy


def handler(event: dict, context) -> dict:
    """
    Lambda Authorizer entry point.

    event keys (TOKEN authorizer):
      - authorizationToken: "Bearer <jwt>"
      - methodArn: "arn:aws:execute-api:..."
    """
    raw_token: str = event.get("authorizationToken", "")
    method_arn: str = event.get("methodArn", "*")

    # Strip "Bearer " prefix
    token = raw_token.removeprefix("Bearer ").strip()
    if not token:
        return _build_policy("Deny", method_arn)

    # Fetch and parse JWKS
    try:
        jwks = _get_jwks()
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(
            json.dumps(jwks["keys"][0])
        )
    except Exception:
        # JWKS fetch failure — fail closed (deny all)
        return _build_policy("Deny", method_arn)

    # Decode and validate JWT
    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
        )
    except jwt.ExpiredSignatureError:
        return _build_policy("Deny", method_arn)
    except jwt.InvalidTokenError:
        return _build_policy("Deny", method_arn)

    # Ensure this is an access token (not a refresh token)
    if payload.get("type") != "access":
        return _build_policy("Deny", method_arn)

    user_id: Optional[str] = payload.get("sub")
    if not user_id:
        return _build_policy("Deny", method_arn)

    return _build_policy("Allow", method_arn, user_id)
