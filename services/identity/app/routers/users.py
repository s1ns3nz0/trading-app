"""Users router — /users/* endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from ..repositories.user_repository import DynamoUserRepository
from ..services.auth_service import AuthError

router = APIRouter()


def get_repo() -> DynamoUserRepository:
    return DynamoUserRepository()


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    totp_enabled: bool


class UpdateProfileRequest(BaseModel):
    username: str | None = None


@router.get("/me", response_model=UserResponse)
async def get_me(request: Request, repo: DynamoUserRepository = Depends(get_repo)):
    user_id = request.state.user_id
    user = await repo.find_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        totp_enabled=user.totp_enabled,
    )


@router.patch("/me", response_model=UserResponse)
async def update_profile(
    body: UpdateProfileRequest,
    request: Request,
    repo: DynamoUserRepository = Depends(get_repo),
):
    user_id = request.state.user_id
    user = await repo.find_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if body.username is not None:
        user.username = body.username

    await repo.update(user)

    return UserResponse(
        id=user.id,
        email=user.email,
        username=user.username,
        totp_enabled=user.totp_enabled,
    )
