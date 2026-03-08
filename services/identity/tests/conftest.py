"""Shared pytest fixtures for identity service tests."""

import pytest
import boto3
from moto import mock_aws
from unittest.mock import AsyncMock

from app.models.user import User, UserStatus


@pytest.fixture(scope="function")
def dynamo_table():
    """Mocked DynamoDB table via moto — isolated per test function."""
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
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                }
            ],
            BillingMode="PAY_PER_REQUEST",
        )
        yield client


@pytest.fixture
def mock_repo():
    """Fully-mocked async UserRepository."""
    repo = AsyncMock()
    repo.find_by_email = AsyncMock(return_value=None)
    repo.find_by_id = AsyncMock(return_value=None)
    repo.save = AsyncMock(side_effect=lambda u: u)
    repo.update = AsyncMock(side_effect=lambda u: u)
    repo.revoke_token = AsyncMock()
    repo.is_token_revoked = AsyncMock(return_value=False)
    repo.save_verification_token = AsyncMock()
    repo.get_verification_token = AsyncMock(return_value=None)
    repo.delete_verification_token = AsyncMock()
    repo.increment_login_attempt = AsyncMock(return_value=1)
    repo.get_login_attempts = AsyncMock(return_value=0)
    repo.activate_user = AsyncMock()
    return repo


@pytest.fixture
def active_user() -> User:
    import bcrypt
    hashed = bcrypt.hashpw(b"correctpassword", bcrypt.gensalt(rounds=4)).decode()
    return User(
        email="alice@example.com",
        username="alice",
        hashed_password=hashed,
        status=UserStatus.ACTIVE,
    )


@pytest.fixture
def pending_user() -> User:
    import bcrypt
    hashed = bcrypt.hashpw(b"correctpassword", bcrypt.gensalt(rounds=4)).decode()
    return User(
        email="bob@example.com",
        username="bob",
        hashed_password=hashed,
        status=UserStatus.PENDING_VERIFICATION,
    )
