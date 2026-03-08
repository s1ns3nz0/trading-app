"""Initial schema: withdrawals + withdrawal_audit_log"""
from alembic import op

revision = "001"
down_revision = None


def upgrade():
    # Schema already exists from deposit-service migration
    op.execute(
        "CREATE TYPE finance.withdrawal_type AS ENUM ('CRYPTO', 'FIAT')"
    )
    op.execute(
        """
        CREATE TYPE finance.withdrawal_status AS ENUM (
            'PENDING', 'PROCESSING', 'EXECUTED', 'REJECTED', 'FAILED', 'CANCELLED'
        )
        """
    )

    op.execute(
        """
        CREATE TABLE finance.withdrawals (
            id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id               VARCHAR(64)               NOT NULL,
            type                  finance.withdrawal_type   NOT NULL,
            asset                 VARCHAR(10)               NOT NULL,
            amount                NUMERIC(20, 8)            NOT NULL,
            status                finance.withdrawal_status NOT NULL DEFAULT 'PENDING',
            to_address            VARCHAR(128),
            tx_hash               VARCHAR(128),
            bank_account_number   VARCHAR(64),
            bank_routing_number   VARCHAR(32),
            rejection_reason      TEXT,
            step_fn_execution_arn VARCHAR(2048),
            reserved_at           TIMESTAMPTZ,
            executed_at           TIMESTAMPTZ,
            expires_at            TIMESTAMPTZ               NOT NULL,
            created_at            TIMESTAMPTZ               NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ               NOT NULL DEFAULT NOW(),

            CONSTRAINT withdrawals_tx_hash_unique UNIQUE (tx_hash),
            CONSTRAINT withdrawals_amount_positive CHECK (amount > 0)
        )
        """
    )

    op.execute(
        "CREATE INDEX idx_withdrawals_user_id "
        "ON finance.withdrawals (user_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_withdrawals_status "
        "ON finance.withdrawals (status, expires_at)"
    )
    op.execute(
        # For AML daily sum query
        "CREATE INDEX idx_withdrawals_aml "
        "ON finance.withdrawals (user_id, asset, status, created_at)"
    )

    op.execute(
        """
        CREATE TABLE finance.withdrawal_audit_log (
            id            BIGSERIAL PRIMARY KEY,
            withdrawal_id UUID                      NOT NULL REFERENCES finance.withdrawals(id),
            from_status   finance.withdrawal_status,
            to_status     finance.withdrawal_status NOT NULL,
            note          TEXT,
            created_at    TIMESTAMPTZ               NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_withdrawal_audit_id "
        "ON finance.withdrawal_audit_log (withdrawal_id, created_at DESC)"
    )


def downgrade():
    op.execute("DROP TABLE IF EXISTS finance.withdrawal_audit_log")
    op.execute("DROP TABLE IF EXISTS finance.withdrawals")
    op.execute("DROP TYPE IF EXISTS finance.withdrawal_status")
    op.execute("DROP TYPE IF EXISTS finance.withdrawal_type")
