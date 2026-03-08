"""
Lambda JWT Authorizer for API Gateway (REQUEST type).

Validates RS256 JWTs issued by the Identity service.
Returns an IAM policy that API Gateway evaluates for authorization.

Environment variables:
  JWT_PUBLIC_KEY  — RSA public key PEM string (from Secrets Manager via Lambda env)
  JWT_ALGORITHM   — always RS256
"""

import json
import os
from typing import Any

import jwt

PUBLIC_KEY = os.environ["JWT_PUBLIC_KEY"]
ALGORITHM = os.environ.get("JWT_ALGORITHM", "RS256")


def handler(event: dict, context: Any) -> dict:
    token = _extract_token(event)

    if not token:
        # API Gateway expects a raise or an explicit Deny
        raise Exception("Unauthorized")

    try:
        payload = jwt.decode(token, PUBLIC_KEY, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise Exception("Unauthorized")
    except jwt.InvalidTokenError:
        raise Exception("Unauthorized")

    if payload.get("type") != "access":
        raise Exception("Unauthorized")

    user_id: str = payload["sub"]
    method_arn: str = event["methodArn"]

    return _build_policy(
        principal_id=user_id,
        effect="Allow",
        resource=_wildcard_arn(method_arn),
        context={"userId": user_id},
    )


def _extract_token(event: dict) -> str | None:
    """Support both header-based and query-string token delivery."""
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    auth_header = headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:]

    # WebSocket connections may pass token in query string
    query = event.get("queryStringParameters") or {}
    return query.get("token")


def _wildcard_arn(method_arn: str) -> str:
    """Convert a specific method ARN to a stage-level wildcard.

    arn:aws:execute-api:region:acct:api-id/stage/method/path
    →  arn:aws:execute-api:region:acct:api-id/stage/*/*
    """
    parts = method_arn.split(":")
    gateway_parts = parts[5].split("/")
    wildcard = "/".join(gateway_parts[:2] + ["*", "*"])
    parts[5] = wildcard
    return ":".join(parts)


def _build_policy(
    principal_id: str,
    effect: str,
    resource: str,
    context: dict | None = None,
) -> dict:
    return {
        "principalId": principal_id,
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
        "context": context or {},
    }
