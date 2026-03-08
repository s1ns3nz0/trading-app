"""Auth router — /auth/* endpoints."""

import base64
from typing import Optional

from cryptography.hazmat.primitives.serialization import load_pem_public_key
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, field_validator

from ..config import settings
from ..models.user import UserStatus
from ..repositories.user_repository import DynamoUserRepository
from ..services.auth_service import AuthService, AuthError

router = APIRouter()


def get_auth_service() -> AuthService:
    return AuthService(user_repo=DynamoUserRepository())


# ──────────────────────────────────────────────
# Request / Response schemas
# ──────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: EmailStr
    username: str
    password: str

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v

    @field_validator("username")
    @classmethod
    def username_alphanumeric(cls, v: str) -> str:
        if not v.replace("_", "").replace("-", "").isalnum():
            raise ValueError("Username may only contain letters, numbers, _ and -")
        if len(v) < 3 or len(v) > 30:
            raise ValueError("Username must be 3-30 characters")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    totp_enabled: bool


class AuthResponse(BaseModel):
    user: UserResponse
    tokens: TokenResponse


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


class VerifyTotpRequest(BaseModel):
    code: str


# ──────────────────────────────────────────────
# JWKS
# ──────────────────────────────────────────────

def _b64url_encode_int(n: int) -> str:
    """Encode an integer as base64url (big-endian, no padding) for JWK."""
    byte_length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(byte_length, "big")).rstrip(b"=").decode()


@router.get("/.well-known/jwks.json")
async def jwks():
    """Return the public RSA key in JWK Set format for token verification."""
    public_key: RSAPublicKey = load_pem_public_key(settings.jwt_public_key.encode())
    pub_numbers = (
        public_key.public_key().public_numbers()
        if hasattr(public_key, "public_key")
        else public_key.public_numbers()
    )
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": "default",
                "n": _b64url_encode_int(pub_numbers.n),
                "e": _b64url_encode_int(pub_numbers.e),
            }
        ]
    }


# ──────────────────────────────────────────────
# Auth endpoints
# ──────────────────────────────────────────────

@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(
    body: RegisterRequest,
    response: Response,
    svc: AuthService = Depends(get_auth_service),
):
    try:
        user = await svc.register(body.email, body.username, body.password)
        await svc.send_verification_email(user.id, user.email)
        access_token, refresh_token = svc._issue_tokens(user.id)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    _set_refresh_cookie(response, refresh_token)

    return AuthResponse(
        user=UserResponse(
            id=user.id,
            email=user.email,
            username=user.username,
            totp_enabled=user.totp_enabled,
        ),
        tokens=TokenResponse(access_token=access_token),
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    body: LoginRequest,
    response: Response,
    svc: AuthService = Depends(get_auth_service),
):
    try:
        access_token, refresh_token = await svc.login(
            body.email, body.password, body.totp_code
        )
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    user = await svc._repo.find_by_email(body.email)
    _set_refresh_cookie(response, refresh_token)

    return AuthResponse(
        user=UserResponse(
            id=user.id,
            email=user.email,
            username=user.username,
            totp_enabled=user.totp_enabled,
        ),
        tokens=TokenResponse(access_token=access_token),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    svc: AuthService = Depends(get_auth_service),
):
    refresh_token = request.cookies.get("refresh_token")
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")

    try:
        access_token, new_refresh_token = await svc.refresh(refresh_token)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    _set_refresh_cookie(response, new_refresh_token)
    return TokenResponse(access_token=access_token)


@router.post("/logout", status_code=204)
async def logout(
    request: Request,
    response: Response,
    svc: AuthService = Depends(get_auth_service),
):
    refresh_token = request.cookies.get("refresh_token")
    if refresh_token:
        await svc.logout(refresh_token)

    response.delete_cookie(
        key="refresh_token",
        httponly=True,
        secure=True,
        samesite="strict",
    )


@router.post("/verify-email", status_code=204)
async def verify_email(
    body: VerifyEmailRequest,
    svc: AuthService = Depends(get_auth_service),
):
    try:
        await svc.verify_email(body.token)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/resend-verification", status_code=204)
async def resend_verification(
    body: ResendVerificationRequest,
    svc: AuthService = Depends(get_auth_service),
):
    user = await svc._repo.find_by_email(body.email)
    if user and user.status == UserStatus.PENDING_VERIFICATION:
        await svc.send_verification_email(user.id, user.email)
    # Always return 204 — don't leak whether email is registered


@router.post("/totp/enable")
async def enable_totp(
    request: Request,
    svc: AuthService = Depends(get_auth_service),
):
    user_id = request.state.user_id  # set by JWTAuthMiddleware
    try:
        secret, provisioning_uri = await svc.enable_totp(user_id)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    return {"secret": secret, "provisioning_uri": provisioning_uri}


@router.post("/totp/verify", status_code=204)
async def verify_totp(
    body: VerifyTotpRequest,
    request: Request,
    svc: AuthService = Depends(get_auth_service),
):
    user_id = request.state.user_id
    try:
        await svc.verify_totp(user_id, body.code)
    except AuthError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


# ──────────────────────────────────────────────
# Cookie helper
# ──────────────────────────────────────────────

def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="strict",
        max_age=settings.refresh_token_ttl_seconds,
        path="/auth/refresh",  # scoped — browser only sends on /auth/refresh
    )
