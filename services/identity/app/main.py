"""Identity Service — FastAPI application entry point."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

from .middleware.auth import JWTAuthMiddleware
from .routers import auth, users
from .config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: warm DynamoDB connection, validate JWKS keys
    yield
    # Shutdown: cleanup (nothing persistent in Lambda)


app = FastAPI(
    title="Identity Service",
    version="1.0.0",
    docs_url="/docs" if settings.environment != "prod" else None,
    redoc_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.add_middleware(JWTAuthMiddleware)

app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(users.router, prefix="/users", tags=["users"])


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "identity"}


# Lambda handler — Mangum adapts ASGI to API Gateway proxy format
handler = Mangum(app, lifespan="off")
