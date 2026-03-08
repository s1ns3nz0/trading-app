"""Initial schema: deposits + deposit_audit_log

Revision ID: 001
Revises: None
Create Date: 2026-03-08
"""
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE SCHEMA IF NOT EXISTS finance")

    op.execute(
        "CREATE TYPE finance.deposit_type AS ENUM ('CRYPTO', 'FIAT')"
    )
    op.execute(
        """
        CREATE TYPE finance.deposit_status AS ENUM (
            'PENDING', 'CONFIRMING', 'CONFIRMED', 'CREDITED', 'FAILED', 'EXPIRED'
        )
        """
    )

    op.execute(
        """
        CREATE TABLE finance.deposits (
            id                     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id                VARCHAR(64)            NOT NULL,
            type                   finance.deposit_type   NOT NULL,
            asset                  VARCHAR(10)            NOT NULL,
            amount                 NUMERIC(20, 8)         NOT NULL,
            status                 finance.deposit_status NOT NULL DEFAULT 'PENDING',
            wallet_address         VARCHAR(128),
            tx_hash                VARCHAR(128),
            bank_reference         VARCHAR(64),
            confirmations          INT                    NOT NULL DEFAULT 0,
            required_confirmations INT                    NOT NULL DEFAULT 0,
            step_fn_execution_arn  VARCHAR(2048),
            credited_at            TIMESTAMPTZ,
            expires_at             TIMESTAMPTZ            NOT NULL,
            created_at             TIMESTAMPTZ            NOT NULL DEFAULT NOW(),
            updated_at             TIMESTAMPTZ            NOT NULL DEFAULT NOW(),

            CONSTRAINT deposits_tx_hash_unique   UNIQUE (tx_hash),
            CONSTRAINT deposits_bank_ref_unique  UNIQUE (bank_reference),
            CONSTRAINT deposits_amount_positive  CHECK (amount > 0)
        )
        """
    )

    op.execute(
        "CREATE INDEX idx_deposits_user_id ON finance.deposits (user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_deposits_status ON finance.deposits (status, expires_at)"
    )
    op.execute(
        "CREATE INDEX idx_deposits_address ON finance.deposits (wallet_address) "
        "WHERE wallet_address IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE finance.deposit_audit_log (
            id          BIGSERIAL PRIMARY KEY,
            deposit_id  UUID                   NOT NULL REFERENCES finance.deposits(id),
            from_status finance.deposit_status,
            to_status   finance.deposit_status NOT NULL,
            note        TEXT,
            created_at  TIMESTAMPTZ            NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_audit_deposit_id "
        "ON finance.deposit_audit_log (deposit_id, created_at DESC)"
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS finance.deposit_audit_log")
    op.execute("DROP TABLE IF EXISTS finance.deposits")
    op.execute("DROP TYPE IF EXISTS finance.deposit_status")
    op.execute("DROP TYPE IF EXISTS finance.deposit_type")
