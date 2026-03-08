"""Initial schema: orders, trades, positions

Revision ID: 001
Revises:
Create Date: 2026-03-08
"""
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         UUID NOT NULL,
            symbol          VARCHAR(20) NOT NULL,
            side            VARCHAR(4) NOT NULL CHECK (side IN ('BUY','SELL')),
            type            VARCHAR(6) NOT NULL CHECK (type IN ('LIMIT','MARKET')),
            status          VARCHAR(10) NOT NULL DEFAULT 'PENDING',
            price           NUMERIC(20,8),
            orig_qty        NUMERIC(20,8) NOT NULL,
            executed_qty    NUMERIC(20,8) NOT NULL DEFAULT 0,
            avg_price       NUMERIC(20,8),
            time_in_force   VARCHAR(3) NOT NULL DEFAULT 'GTC',
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT orders_price_required CHECK (type = 'MARKET' OR price IS NOT NULL)
        );

        CREATE INDEX IF NOT EXISTS idx_orders_user_symbol
            ON orders (user_id, symbol, created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_orders_symbol_status
            ON orders (symbol, status)
            WHERE status IN ('OPEN','PARTIAL');

        CREATE TABLE IF NOT EXISTS trades (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            symbol          VARCHAR(20) NOT NULL,
            buy_order_id    UUID NOT NULL REFERENCES orders(id),
            sell_order_id   UUID NOT NULL REFERENCES orders(id),
            price           NUMERIC(20,8) NOT NULL,
            qty             NUMERIC(20,8) NOT NULL,
            buyer_fee       NUMERIC(20,8) NOT NULL DEFAULT 0,
            seller_fee      NUMERIC(20,8) NOT NULL DEFAULT 0,
            executed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        CREATE INDEX IF NOT EXISTS idx_trades_buy_order
            ON trades (buy_order_id);

        CREATE INDEX IF NOT EXISTS idx_trades_sell_order
            ON trades (sell_order_id);

        CREATE INDEX IF NOT EXISTS idx_trades_symbol_time
            ON trades (symbol, executed_at DESC);

        CREATE TABLE IF NOT EXISTS positions (
            user_id         UUID NOT NULL,
            asset           VARCHAR(10) NOT NULL,
            available       NUMERIC(20,8) NOT NULL DEFAULT 0,
            locked          NUMERIC(20,8) NOT NULL DEFAULT 0,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, asset),
            CONSTRAINT positions_non_negative CHECK (available >= 0 AND locked >= 0)
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS positions, trades, orders CASCADE;")
