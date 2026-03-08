from fastapi import HTTPException, Request

INTERNAL_PATHS = ("/health",)


async def require_user_id(request: Request) -> str:
    if any(request.url.path.startswith(p) for p in INTERNAL_PATHS):
        return ""
    user_id = request.headers.get("X-User-Id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing X-User-Id header")
    return user_id
