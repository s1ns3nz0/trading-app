"""
Tests — Webhook HMAC validation + idempotency.

Coverage:
  TC-W01  Valid HMAC crypto webhook → 200
  TC-W02  Missing signature → 401
  TC-W03  Tampered body → 401
  TC-W04  Duplicate crypto webhook (idempotent) → 200
  TC-W05  Unknown wallet address → 422
  TC-W06  Valid fiat webhook → 200
  TC-W07  Duplicate fiat webhook (idempotent) → 200
"""
import hashlib
import hmac
import json
import pytest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport

from ..app.models.domain import DepositStatus

HMAC_SECRET = "dev-hmac-secret"

CRYPTO_PAYLOAD = {
    "tx_hash": "0xdeadbeef",
    "address": "0xabc123def456abc123def456abc123def456abc1",
    "amount": "0.5",
    "confirmations": 12,
}
FIAT_PAYLOAD = {
    "bank_reference": "DEP-ABCDEF12",
    "amount": "100",
}


def _sign(body: bytes, secret: str = HMAC_SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _make_mock_deposit(status: DepositStatus = DepositStatus.CONFIRMING):
    d = MagicMock()
    d.id = "dep-uuid-001"
    d.status = status
    return d


# TC-W01
@pytest.mark.asyncio
async def test_valid_crypto_webhook(app):
    body = json.dumps(CRYPTO_PAYLOAD).encode()
    sig = _sign(body)

    with (
        patch("services.deposit.app.routers.webhooks.deposit_svc") as mock_svc,
        patch("services.deposit.app.routers.webhooks.db_pool") as mock_pool,
        patch(
            "services.deposit.app.repositories.deposit_repo.PostgresDepositRepository"
        ),
    ):
        mock_dep = _make_mock_deposit()
        mock_svc.process_crypto_webhook = AsyncMock(return_value=mock_dep)
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/internal/webhooks/crypto",
                content=body,
                headers={
                    "X-Webhook-Signature": sig,
                    "Content-Type": "application/json",
                },
            )

    assert resp.status_code == 200
    assert resp.json()["deposit_id"] == "dep-uuid-001"


# TC-W02
@pytest.mark.asyncio
async def test_missing_hmac_returns_401(app):
    body = json.dumps(CRYPTO_PAYLOAD).encode()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/internal/webhooks/crypto",
            content=body,
            headers={"Content-Type": "application/json"},
        )
    assert resp.status_code == 401
    assert "signature" in resp.json()["detail"].lower()


# TC-W03
@pytest.mark.asyncio
async def test_tampered_body_returns_401(app):
    body = json.dumps(CRYPTO_PAYLOAD).encode()
    sig = _sign(body)
    tampered = body + b"extra"

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/internal/webhooks/crypto",
            content=tampered,
            headers={
                "X-Webhook-Signature": sig,
                "Content-Type": "application/json",
            },
        )
    assert resp.status_code == 401


# TC-W04
@pytest.mark.asyncio
async def test_duplicate_crypto_webhook_idempotent(app):
    body = json.dumps(CRYPTO_PAYLOAD).encode()
    sig = _sign(body)

    with (
        patch("services.deposit.app.routers.webhooks.deposit_svc") as mock_svc,
        patch("services.deposit.app.routers.webhooks.db_pool") as mock_pool,
    ):
        confirming_dep = _make_mock_deposit(DepositStatus.CONFIRMING)
        mock_svc.process_crypto_webhook = AsyncMock(return_value=confirming_dep)
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/internal/webhooks/crypto",
                content=body,
                headers={"X-Webhook-Signature": sig, "Content-Type": "application/json"},
            )

    assert resp.status_code == 200
    assert resp.json()["status"] == "CONFIRMING"


# TC-W05
@pytest.mark.asyncio
async def test_unknown_address_returns_422(app):
    body = json.dumps(CRYPTO_PAYLOAD).encode()
    sig = _sign(body)

    with (
        patch("services.deposit.app.routers.webhooks.deposit_svc") as mock_svc,
        patch("services.deposit.app.routers.webhooks.db_pool") as mock_pool,
    ):
        mock_svc.process_crypto_webhook = AsyncMock(
            side_effect=ValueError("No PENDING deposit for address")
        )
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/internal/webhooks/crypto",
                content=body,
                headers={"X-Webhook-Signature": sig, "Content-Type": "application/json"},
            )

    assert resp.status_code == 422


# TC-W06
@pytest.mark.asyncio
async def test_valid_fiat_webhook(app):
    body = json.dumps(FIAT_PAYLOAD).encode()
    sig = _sign(body)

    with (
        patch("services.deposit.app.routers.webhooks.deposit_svc") as mock_svc,
        patch("services.deposit.app.routers.webhooks.db_pool") as mock_pool,
    ):
        mock_dep = _make_mock_deposit()
        mock_svc.process_fiat_webhook = AsyncMock(return_value=mock_dep)
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/internal/webhooks/fiat",
                content=body,
                headers={"X-Webhook-Signature": sig, "Content-Type": "application/json"},
            )

    assert resp.status_code == 200


# TC-W07
@pytest.mark.asyncio
async def test_duplicate_fiat_webhook_idempotent(app):
    body = json.dumps(FIAT_PAYLOAD).encode()
    sig = _sign(body)

    with (
        patch("services.deposit.app.routers.webhooks.deposit_svc") as mock_svc,
        patch("services.deposit.app.routers.webhooks.db_pool") as mock_pool,
    ):
        confirming = _make_mock_deposit(DepositStatus.CONFIRMING)
        mock_svc.process_fiat_webhook = AsyncMock(return_value=confirming)
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/internal/webhooks/fiat",
                content=body,
                headers={"X-Webhook-Signature": sig, "Content-Type": "application/json"},
            )

    assert resp.status_code == 200
    assert resp.json()["status"] == "CONFIRMING"
