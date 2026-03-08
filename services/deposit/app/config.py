from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    db_url: str = "postgresql://localhost/finance"
    aws_region: str = "ap-northeast-2"
    step_fn_arn: str = ""
    eventbridge_bus_name: str = "finance-events"
    spot_trading_internal_url: str = "http://spot-trading:8000"
    internal_token: str = "dev-internal-token"
    webhook_hmac_secret: str = "dev-hmac-secret"
    deposit_expiry_hours: int = 24

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
