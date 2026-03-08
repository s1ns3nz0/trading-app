"""Runtime configuration loaded from environment / AWS SSM."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    environment: str = "dev"

    # JWT — RS256 private key (PEM string injected from Secrets Manager)
    jwt_private_key: str
    jwt_public_key: str
    jwt_algorithm: str = "RS256"
    access_token_ttl_seconds: int = 3600      # 1 hour
    refresh_token_ttl_seconds: int = 604800   # 7 days

    # DynamoDB
    dynamodb_table_name: str = "trading-identity"
    aws_region: str = "ap-northeast-2"

    # CORS
    allowed_origins: list[str] = ["https://app.trading-platform.com"]

    # TOTP
    totp_issuer: str = "TradingPlatform"

    # SES — email verification
    ses_enabled: bool = False                             # False in dev/test; True in prod
    ses_from_address: str = "noreply@trading-platform.com"
    app_base_url: str = "https://app.trading-platform.com"

    # Bcrypt cost factor
    bcrypt_rounds: int = 12

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
