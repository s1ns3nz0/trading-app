from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Kafka consumer
    kafka_brokers: str = "localhost:9092"
    kafka_consumer_group: str = "market-data-router"
    kafka_topics: str = "market.ticker.v1,market.orderbook.v1,market.trades.v1"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # EventBridge
    event_bus_name: str = "market-data-prod"
    aws_region: str = "ap-northeast-2"

    # TTLs (seconds) — match design doc
    ticker_ttl: int = 60
    orderbook_ttl: int = 10
    trades_ttl: int = 300
    trades_max_length: int = 50

    log_level: str = "INFO"

    @property
    def topic_list(self) -> list[str]:
        return [t.strip() for t in self.kafka_topics.split(",") if t.strip()]


settings = Settings()
