from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    kafka_brokers: str       = "localhost:9092"
    db_url: str              = "postgresql://spot_admin:@localhost:5432/spot_trading"
    redis_url: str           = "redis://localhost:6379"
    jwt_public_key: str      = ""
    supported_symbols: list[str] = ["BTC-USDT", "ETH-USDT", "SOL-USDT", "BNB-USDT"]
    price_deviation_limit: float = 0.10
    internal_token: str = "dev-internal-token"

    class Config:
        env_file = ".env"


settings = Settings()
