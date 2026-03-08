from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    redis_url: str = "redis://localhost:6379"
    candles_table: str = "market-data-candles"
    aws_region: str = "ap-northeast-2"
    symbols: str = "BTC-USDT,ETH-USDT,SOL-USDT,BNB-USDT"
    log_level: str = "INFO"

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip() for s in self.symbols.split(",") if s.strip()]


settings = Settings()
