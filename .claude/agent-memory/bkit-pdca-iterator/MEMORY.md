# PDCA Iterator Agent Memory

## Project: trading-app (crypto-trading-platform)

### market-data-service Iteration History
- Iteration 1 (Check): 87.3% match rate (117.0/134) — gap analysis in docs/03-analysis/market-data-service.analysis.md
- Iteration 2 (Act): 89.9% match rate (120.5/134) — fixes applied 2026-03-08

### Key Gaps Fixed in Iteration 2
- G1: float→str in domain models (market_data.py + binance_translator.py)
- G2: timestamp: int added to Ticker, OrderBook, Trade (note: design uses datetime, task spec uses int)
- G9: Redis pub/sub channel pattern `ws:{channel}:{symbol}` in redis_handler.py
- G12: Pydantic schemas created at api/app/schemas.py; response_model added to ticker + candles routers
- G8 candle: ConditionalCheckFailedException handled gracefully in candle-builder/handler.py
- G17: pydantic==2.10.3 + mangum==0.19.0 added to api/requirements.txt

### Remaining Gaps (0.1% below 90% threshold)
- G2 (partial): timestamp int vs datetime type — task spec said int, design says datetime
- G7: @classmethod vs @staticmethod in BinanceTranslator (LOW, no functional difference)
- G3: Trade payload key "qty" vs "quantity" (MED)
- G10: Orderbook ZADD member format missing price (LOW)
- G11: Pipeline transaction=True vs False (LOW)

### Key File Paths
- Domain models: services/market-data/ingester/app/models/market_data.py
- ACL translator: services/market-data/ingester/app/acl/binance_translator.py
- Redis handler: services/market-data/router/app/handlers/redis_handler.py
- API schemas: services/market-data/api/app/schemas.py (created in iteration 2)
- Candle builder: services/market-data/candle-builder/handler.py
- Analysis report: docs/03-analysis/market-data-service.analysis.md
- Design doc: docs/02-design/features/market-data-service.design.md

### Patterns Learned
- Binance wire format sends all price/quantity fields as strings — never cast to float
- Redis pub/sub channel pattern must be `ws:{channel_type}:{symbol}` (not `market:{symbol}:{type}`)
- Lambda handlers (candle-builder) need explicit ConditionalCheckFailedException handling for idempotency
- Pydantic schemas should go in api/app/schemas.py, not inline in routers
