"""AuthService — login, register, token lifecycle."""

import secrets
from datetime import datetime, timedelta, UTC
from typing import Optional

import bcrypt
import boto3
import jwt
import pyotp

from ..config import settings
from ..models.user import User, UserStatus
from ..repositories.user_repository import UserRepository

MAX_LOGIN_ATTEMPTS = 5


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class AuthService:
    def __init__(self, user_repo: UserRepository):
        self._repo = user_repo
        self._ses_client = boto3.client("ses", region_name=settings.aws_region)

    async def register(self, email: str, username: str, password: str) -> User:
        existing = await self._repo.find_by_email(email)
        if existing:
            raise AuthError("Email already registered", status_code=409)

        hashed = bcrypt.hashpw(
            password.encode(), bcrypt.gensalt(rounds=settings.bcrypt_rounds)
        ).decode()

        user = User(email=email, username=username, hashed_password=hashed)
        return await self._repo.save(user)

    async def login(
        self,
        email: str,
        password: str,
        totp_code: Optional[str] = None,
    ) -> tuple[str, str]:
        """Returns (access_token, refresh_token)."""
        # Rate limit check BEFORE credential verification (avoids bcrypt timing leak)
        attempts = await self._repo.get_login_attempts(email)
        if attempts >= MAX_LOGIN_ATTEMPTS:
            raise AuthError(
                "Too many failed attempts. Try again in 15 minutes.",
                status_code=429,
            )

        user = await self._repo.find_by_email(email)

        # Constant-time comparison even when user not found (prevents timing attacks)
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

    async def refresh(self, refresh_token: str) -> tuple[str, str]:
        """Validates refresh token, checks revocation, rotates token pair."""
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

        # Revoke old refresh token (rotation — prevents reuse)
        exp_timestamp = int(payload["exp"])
        await self._repo.revoke_token(jti, user_id, exp_timestamp)

        return self._issue_tokens(user_id)

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

    async def send_verification_email(self, user_id: str, email: str) -> None:
        """Generate token, save to DynamoDB, send SES email."""
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
                        "Text": {
                            "Data": (
                                f"Welcome to TradingPlatform!\n\n"
                                f"Click the link below to verify your email address:\n"
                                f"{verify_url}\n\n"
                                f"This link expires in 24 hours."
                            )
                        }
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

    def _issue_tokens(self, user_id: str) -> tuple[str, str]:
        now = datetime.now(UTC)

        access_payload = {
            "sub": user_id,
            "type": "access",
            "iat": now,
            "exp": now + timedelta(seconds=settings.access_token_ttl_seconds),
            "jti": secrets.token_hex(16),
        }

        refresh_payload = {
            "sub": user_id,
            "type": "refresh",
            "iat": now,
            "exp": now + timedelta(seconds=settings.refresh_token_ttl_seconds),
            "jti": secrets.token_hex(16),
        }

        access_token = jwt.encode(
            access_payload, settings.jwt_private_key, algorithm=settings.jwt_algorithm
        )
        refresh_token = jwt.encode(
            refresh_payload, settings.jwt_private_key, algorithm=settings.jwt_algorithm
        )

        return access_token, refresh_token

    async def enable_totp(self, user_id: str) -> tuple[str, str]:
        """Generates TOTP secret and returns (secret, provisioning_uri)."""
        user = await self._repo.find_by_id(user_id)
        if not user:
            raise AuthError("User not found", status_code=404)

        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        provisioning_uri = totp.provisioning_uri(
            name=user.email,
            issuer_name=settings.totp_issuer,
        )

        user.totp_secret = secret
        await self._repo.update(user)

        return secret, provisioning_uri

    async def verify_totp(self, user_id: str, code: str) -> None:
        """Activates TOTP after verifying the first code."""
        user = await self._repo.find_by_id(user_id)
        if not user:
            raise AuthError("User not found", status_code=404)
        if not user.totp_secret:
            raise AuthError("TOTP not initialized", status_code=400)

        totp = pyotp.TOTP(user.totp_secret)
        if not totp.verify(code, valid_window=1):
            raise AuthError("Invalid TOTP code")

        user.totp_enabled = True
        await self._repo.update(user)
