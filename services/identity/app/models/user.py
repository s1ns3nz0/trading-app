"""User domain model — pure Python, no infrastructure dependencies."""

from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import StrEnum
from typing import Optional
import uuid


class UserStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"
    PENDING_VERIFICATION = "pending_verification"


@dataclass
class User:
    email: str
    username: str
    hashed_password: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: UserStatus = UserStatus.PENDING_VERIFICATION
    totp_secret: Optional[str] = None
    totp_enabled: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dynamo_item(self) -> dict:
        return {
            "PK": f"USER#{self.id}",
            "SK": "PROFILE",
            "GSI1PK": f"EMAIL#{self.email.lower()}",
            "GSI1SK": "USER",
            "id": self.id,
            "email": self.email.lower(),
            "username": self.username,
            "hashed_password": self.hashed_password,
            "status": self.status.value,
            "totp_secret": self.totp_secret,
            "totp_enabled": self.totp_enabled,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dynamo_item(cls, item: dict) -> "User":
        return cls(
            id=item["id"],
            email=item["email"],
            username=item["username"],
            hashed_password=item["hashed_password"],
            status=UserStatus(item["status"]),
            totp_secret=item.get("totp_secret"),
            totp_enabled=item.get("totp_enabled", False),
            created_at=datetime.fromisoformat(item["created_at"]),
            updated_at=datetime.fromisoformat(item["updated_at"]),
        )
