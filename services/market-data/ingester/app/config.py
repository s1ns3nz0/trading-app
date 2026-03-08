from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Kafka
    kafka_brokers: str = "localhost:9092"

    # Binance WebSocket
    binance_ws_base_url: str = "wss://stream.binance.com:9443"
    symbols: str = "BTC-USDT,ETH-USDT,SOL-USDT,BNB-USDT"
    # Streams per symbol: ticker + depth20 + trade + kline_1m
    streams_per_symbol: list[str] = ["@ticker", "@depth20@100ms", "@trade", "@kline_1m"]

    # Reconnect
    reconnect_min_wait: float = 1.0    # seconds
    reconnect_max_wait: float = 60.0   # seconds

    log_level: str = "INFO"

    @property
    def symbol_list(self) -> list[str]:
        return [s.strip() for s in self.symbols.split(",") if s.strip()]

    @property
    def binance_stream_names(self) -> list[str]:
        """Build combined stream names for the /stream?streams= endpoint."""
        names = []
        for sym in self.symbol_list:
            # Convert BTC-USDT → btcusdt for Binance stream names
            b_sym = sym.replace("-", "").lower()
            for stream_suffix in self.streams_per_symbol:
                names.append(f"{b_sym}{stream_suffix}")
        return names


settings = Settings()
