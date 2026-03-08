"""Unit tests for Lambda Authorizer."""

import json
import pytest
from unittest.mock import patch, MagicMock
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend


# ──────────────────────────────────────────────
# Fixtures — generate a real RSA key pair for tests
# ──────────────────────────────────────────────

@pytest.fixture(scope="module")
def rsa_keys():
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    public_key = private_key.public_key()
    return private_key, public_key


@pytest.fixture(scope="module")
def mock_jwks(rsa_keys):
    _, public_key = rsa_keys
    return {"keys": [json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(public_key))]}


@pytest.fixture
def valid_access_token(rsa_keys):
    private_key, _ = rsa_keys
    from datetime import datetime, timedelta, UTC
    import secrets
    payload = {
        "sub": "user-abc-123",
        "type": "access",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(hours=1),
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


@pytest.fixture
def refresh_token_jwt(rsa_keys):
    private_key, _ = rsa_keys
    from datetime import datetime, timedelta, UTC
    import secrets
    payload = {
        "sub": "user-abc-123",
        "type": "refresh",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(days=7),
        "jti": secrets.token_hex(16),
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


# ──────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────

METHOD_ARN = "arn:aws:execute-api:ap-northeast-2:123456789012:abc123/prod/GET/spot/orders"


def _invoke(token: str, mock_jwks_data: dict) -> dict:
    """Helper: invoke authorizer handler with mocked JWKS."""
    with patch("authorizer.handler._get_jwks", return_value=mock_jwks_data):
        from authorizer.handler import handler
        return handler(
            {"authorizationToken": f"Bearer {token}", "methodArn": METHOD_ARN},
            None,
        )


def test_missing_token_returns_deny():
    from authorizer.handler import handler
    result = handler({"authorizationToken": "", "methodArn": METHOD_ARN}, None)
    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"


def test_invalid_jwt_returns_deny(mock_jwks):
    result = _invoke("not.a.valid.jwt", mock_jwks)
    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"


def test_valid_access_token_returns_allow(valid_access_token, mock_jwks):
    result = _invoke(valid_access_token, mock_jwks)
    assert result["policyDocument"]["Statement"][0]["Effect"] == "Allow"
    assert result["context"]["userId"] == "user-abc-123"


def test_refresh_token_type_returns_deny(refresh_token_jwt, mock_jwks):
    """Refresh tokens must not be usable as API auth tokens."""
    result = _invoke(refresh_token_jwt, mock_jwks)
    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"


def test_jwks_fetch_failure_returns_deny():
    from authorizer.handler import handler
    with patch("authorizer.handler._get_jwks", side_effect=Exception("Network error")):
        result = handler(
            {"authorizationToken": "Bearer sometoken", "methodArn": METHOD_ARN},
            None,
        )
    assert result["policyDocument"]["Statement"][0]["Effect"] == "Deny"


def test_allow_policy_includes_user_id_context(valid_access_token, mock_jwks):
    result = _invoke(valid_access_token, mock_jwks)
    assert "context" in result
    assert "userId" in result["context"]
    assert result["context"]["userId"] == "user-abc-123"


def test_principal_id_set_for_allow(valid_access_token, mock_jwks):
    result = _invoke(valid_access_token, mock_jwks)
    assert result["principalId"] == "user-abc-123"


def test_principal_id_anonymous_for_deny():
    from authorizer.handler import handler
    result = handler({"authorizationToken": "", "methodArn": METHOD_ARN}, None)
    assert result["principalId"] == "anonymous"
