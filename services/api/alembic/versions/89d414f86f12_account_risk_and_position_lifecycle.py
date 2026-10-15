"""Persist risk baselines and permit reopened position lifecycles.

Revision ID: 89d414f86f12
Revises: 572407dc9569
"""

import sqlalchemy as sa
from alembic import op

revision = "89d414f86f12"
down_revision = "572407dc9569"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("accounts", sa.Column("peak_equity", sa.Numeric(38, 18), nullable=True))
    op.add_column(
        "accounts", sa.Column("daily_baseline_equity", sa.Numeric(38, 18), nullable=True)
    )
    op.add_column("accounts", sa.Column("risk_day", sa.Date(), nullable=True))
    op.add_column(
        "positions",
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.execute("UPDATE accounts SET peak_equity = cash WHERE peak_equity IS NULL")
    op.execute(
        "UPDATE accounts SET daily_baseline_equity = cash WHERE daily_baseline_equity IS NULL"
    )
    op.drop_constraint("positions_account_id_symbol_key", "positions", type_="unique")
    op.create_index(
        "uq_positions_open_account_symbol",
        "positions",
        ["account_id", "symbol"],
        unique=True,
        postgresql_where=sa.text("state = 'OPEN'"),
    )
    op.create_unique_constraint(
        "uq_funding_payment_position_event",
        "funding_payments",
        ["position_id", "event_at"],
    )
    op.execute(
        "CREATE TRIGGER funding_payments_append_only BEFORE UPDATE OR DELETE ON funding_payments "
        "FOR EACH ROW EXECUTE FUNCTION reject_evidence_mutation()"
    )
    op.execute(
        "CREATE TRIGGER risk_evaluations_append_only BEFORE UPDATE OR DELETE ON risk_evaluations "
        "FOR EACH ROW EXECUTE FUNCTION reject_evidence_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS risk_evaluations_append_only ON risk_evaluations")
    op.execute("DROP TRIGGER IF EXISTS funding_payments_append_only ON funding_payments")
    op.drop_constraint(
        "uq_funding_payment_position_event", "funding_payments", type_="unique"
    )
    op.drop_index("uq_positions_open_account_symbol", table_name="positions")
    op.create_unique_constraint(
        "positions_account_id_symbol_key", "positions", ["account_id", "symbol"]
    )
    op.drop_column("accounts", "risk_day")
    op.drop_column("accounts", "daily_baseline_equity")
    op.drop_column("accounts", "peak_equity")
    op.drop_column("positions", "opened_at")
