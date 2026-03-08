"""DynamoDB-backed UserRepository — single-table design."""

import time
from abc import ABC, abstractmethod
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from ..config import settings
from ..models.user import User


class UserRepository(ABC):
    @abstractmethod
    async def find_by_id(self, user_id: str) -> Optional[User]: ...

    @abstractmethod
    async def find_by_email(self, email: str) -> Optional[User]: ...

    @abstractmethod
    async def save(self, user: User) -> User: ...

    @abstractmethod
    async def update(self, user: User) -> User: ...

    # ── Token revocation ──────────────────────────────────────────────────────
    @abstractmethod
    async def revoke_token(self, jti: str, user_id: str, exp_timestamp: int) -> None: ...

    @abstractmethod
    async def is_token_revoked(self, jti: str) -> bool: ...

    # ── Email verification ────────────────────────────────────────────────────
    @abstractmethod
    async def save_verification_token(self, token: str, user_id: str) -> None: ...

    @abstractmethod
    async def get_verification_token(self, token: str) -> Optional[str]: ...  # returns user_id

    @abstractmethod
    async def delete_verification_token(self, token: str) -> None: ...

    @abstractmethod
    async def activate_user(self, user_id: str) -> None: ...

    # ── Rate limiting ─────────────────────────────────────────────────────────
    @abstractmethod
    async def increment_login_attempt(self, email: str) -> int: ...  # returns new count

    @abstractmethod
    async def get_login_attempts(self, email: str) -> int: ...


class DynamoUserRepository(UserRepository):
    def __init__(self):
        self._client = boto3.client("dynamodb", region_name=settings.aws_region)
        self._table = settings.dynamodb_table_name

    # ── Core user CRUD ────────────────────────────────────────────────────────

    async def find_by_id(self, user_id: str) -> Optional[User]:
        try:
            response = self._client.get_item(
                TableName=self._table,
                Key={
                    "PK": {"S": f"USER#{user_id}"},
                    "SK": {"S": "PROFILE"},
                },
                ConsistentRead=True,
            )
        except ClientError:
            return None

        item = response.get("Item")
        if not item:
            return None

        return User.from_dynamo_item(self._deserialize(item))

    async def find_by_email(self, email: str) -> Optional[User]:
        try:
            response = self._client.query(
                TableName=self._table,
                IndexName="GSI1",
                KeyConditionExpression="GSI1PK = :pk AND GSI1SK = :sk",
                ExpressionAttributeValues={
                    ":pk": {"S": f"EMAIL#{email.lower()}"},
                    ":sk": {"S": "USER"},
                },
                Limit=1,
            )
        except ClientError:
            return None

        items = response.get("Items", [])
        if not items:
            return None

        return User.from_dynamo_item(self._deserialize(items[0]))

    async def save(self, user: User) -> User:
        item = user.to_dynamo_item()
        self._client.put_item(
            TableName=self._table,
            Item=self._serialize(item),
            ConditionExpression="attribute_not_exists(PK)",  # prevent overwrites
        )
        return user

    async def update(self, user: User) -> User:
        item = user.to_dynamo_item()
        self._client.put_item(
            TableName=self._table,
            Item=self._serialize(item),
        )
        return user

    # ── Token revocation ──────────────────────────────────────────────────────

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

    # ── Email verification ────────────────────────────────────────────────────

    async def save_verification_token(self, token: str, user_id: str) -> None:
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

    async def activate_user(self, user_id: str) -> None:
        self._client.update_item(
            TableName=self._table,
            Key={"PK": {"S": f"USER#{user_id}"}, "SK": {"S": "PROFILE"}},
            UpdateExpression="SET #s = :active",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":active": {"S": "active"}},
        )

    # ── Rate limiting ─────────────────────────────────────────────────────────

    async def increment_login_attempt(self, email: str) -> int:
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

    # ── Serialization helpers ─────────────────────────────────────────────────

    @staticmethod
    def _serialize(item: dict) -> dict:
        """Convert plain Python types to DynamoDB attribute format."""
        result = {}
        for k, v in item.items():
            if v is None:
                result[k] = {"NULL": True}
            elif isinstance(v, bool):
                result[k] = {"BOOL": v}
            elif isinstance(v, str):
                result[k] = {"S": v}
            elif isinstance(v, (int, float)):
                result[k] = {"N": str(v)}
        return result

    @staticmethod
    def _deserialize(item: dict) -> dict:
        """Convert DynamoDB attribute format to plain Python types."""
        result = {}
        for k, v in item.items():
            if "S" in v:
                result[k] = v["S"]
            elif "N" in v:
                result[k] = float(v["N"])
            elif "BOOL" in v:
                result[k] = v["BOOL"]
            elif "NULL" in v:
                result[k] = None
        return result
