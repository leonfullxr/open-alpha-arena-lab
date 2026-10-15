"""funding boundary evidence and idempotent settlement outcomes

Revision ID: b35a4d9c12ef
Revises: a2d8d10b5491
Create Date: 2026-10-15 13:30:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "b35a4d9c12ef"
down_revision = "a2d8d10b5491"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("market_quotes", sa.Column("oracle_px", sa.Numeric(38, 18)))
    op.add_column("market_quotes", sa.Column("context_received_at", sa.DateTime(timezone=True)))
    op.add_column("positions", sa.Column("closed_at", sa.DateTime(timezone=True)))
    op.execute(
        "UPDATE positions SET closed_at = now() WHERE state = 'CLOSED' AND closed_at IS NULL"
    )
    op.create_check_constraint(
        "ck_positions_closed_at_state",
        "positions",
        "(state = 'CLOSED') = (closed_at is not null)",
    )

    op.alter_column("funding_payments", "rate", nullable=True)
    op.alter_column("funding_payments", "amount", nullable=True)
    op.add_column("funding_payments", sa.Column("oracle_px", sa.Numeric(38, 18)))
    op.add_column("funding_payments", sa.Column("evidence_id", sa.String(36)))
    op.add_column(
        "funding_payments",
        sa.Column("status", sa.String(12), nullable=False, server_default="PAID"),
    )
    op.add_column("funding_payments", sa.Column("reason", sa.String(80)))
    op.create_check_constraint(
        "ck_funding_payment_status",
        "funding_payments",
        "status in ('PAID','SKIPPED')",
    )
    op.create_check_constraint(
        "ck_funding_payment_amount_status",
        "funding_payments",
        "(status = 'PAID') = (amount is not null)",
    )
    op.create_check_constraint(
        "ck_funding_payment_paid_basis",
        "funding_payments",
        "status != 'PAID' or rate is not null",
    )

    op.create_table(
        "funding_boundary_tasks",
        sa.Column("boundary_at", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expected_symbols", sa.JSON(), nullable=False),
        sa.Column("oracle_quote_set_id", sa.String(36)),
        sa.Column("oracle_snapshot_id", sa.String(36)),
        sa.Column("context_received_at", sa.DateTime(timezone=True)),
        sa.Column("next_poll_at", sa.DateTime(timezone=True)),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capture_owner", sa.String(80)),
        sa.Column("capture_lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("poll_owner", sa.String(80)),
        sa.Column("poll_lease_expires_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status in ('CAPTURE_PENDING','PENDING','READY','UNAVAILABLE')"),
        sa.ForeignKeyConstraint(["oracle_quote_set_id"], ["quote_sets.id"]),
        sa.ForeignKeyConstraint(["oracle_snapshot_id"], ["market_snapshots.id"]),
    )
    op.create_table(
        "funding_rate_evidence",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("boundary_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("rate", sa.Numeric(38, 18)),
        sa.Column("history_event_at", sa.DateTime(timezone=True)),
        sa.Column("raw_record_bytes", sa.LargeBinary()),
        sa.Column("sha256", sa.String(64)),
        sa.CheckConstraint("status in ('READY','UNAVAILABLE')"),
        sa.CheckConstraint(
            "(status = 'READY') = (rate is not null and history_event_at is not null "
            "and raw_record_bytes is not null and sha256 is not null)"
        ),
        sa.UniqueConstraint(
            "symbol", "boundary_at", name="uq_funding_rate_evidence_symbol_boundary"
        ),
    )
    op.create_foreign_key(
        "fk_funding_payment_evidence",
        "funding_payments",
        "funding_rate_evidence",
        ["evidence_id"],
        ["id"],
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "CREATE FUNCTION reject_funding_evidence_mutation() RETURNS trigger "
            "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'funding evidence is append-only'; END $$"
        )
        op.execute(
            "CREATE TRIGGER funding_rate_evidence_append_only BEFORE UPDATE OR DELETE "
            "ON funding_rate_evidence FOR EACH ROW EXECUTE FUNCTION "
            "reject_funding_evidence_mutation()"
        )
        op.execute(
            "CREATE FUNCTION protect_position_basis() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN IF NEW.account_id IS DISTINCT FROM OLD.account_id OR "
            "NEW.symbol IS DISTINCT FROM OLD.symbol OR NEW.side IS DISTINCT FROM OLD.side OR "
            "NEW.quantity IS DISTINCT FROM OLD.quantity OR "
            "NEW.average_entry IS DISTINCT FROM OLD.average_entry OR "
            "NEW.opened_at IS DISTINCT FROM OLD.opened_at THEN "
            "RAISE EXCEPTION 'position basis is immutable'; END IF; "
            "IF OLD.closed_at IS NOT NULL AND NEW.closed_at IS DISTINCT FROM OLD.closed_at THEN "
            "RAISE EXCEPTION 'position close time is immutable'; END IF; "
            "IF OLD.state = 'CLOSED' AND NEW.state != 'CLOSED' THEN "
            "RAISE EXCEPTION 'closed positions cannot be reopened'; END IF; RETURN NEW; END $$"
        )
        op.execute(
            "CREATE TRIGGER positions_immutable_basis BEFORE UPDATE ON positions "
            "FOR EACH ROW EXECUTE FUNCTION protect_position_basis()"
        )
        op.execute(
            "CREATE FUNCTION protect_funding_oracle_pin() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN IF OLD.oracle_quote_set_id IS NOT NULL AND ("
            "NEW.oracle_quote_set_id IS DISTINCT FROM OLD.oracle_quote_set_id OR "
            "NEW.oracle_snapshot_id IS DISTINCT FROM OLD.oracle_snapshot_id OR "
            "NEW.context_received_at IS DISTINCT FROM OLD.context_received_at) THEN "
            "RAISE EXCEPTION 'funding oracle evidence is pinned'; END IF; RETURN NEW; END $$"
        )
        op.execute(
            "CREATE TRIGGER funding_boundary_oracle_pinned BEFORE UPDATE ON funding_boundary_tasks "
            "FOR EACH ROW EXECUTE FUNCTION protect_funding_oracle_pin()"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS funding_boundary_oracle_pinned ON funding_boundary_tasks"
        )
        op.execute("DROP FUNCTION IF EXISTS protect_funding_oracle_pin()")
        op.execute("DROP TRIGGER IF EXISTS positions_immutable_basis ON positions")
        op.execute("DROP FUNCTION IF EXISTS protect_position_basis()")
        op.execute(
            "DROP TRIGGER IF EXISTS funding_rate_evidence_append_only ON funding_rate_evidence"
        )
        op.execute("DROP FUNCTION IF EXISTS reject_funding_evidence_mutation()")
    op.drop_constraint("fk_funding_payment_evidence", "funding_payments", type_="foreignkey")
    op.drop_table("funding_rate_evidence")
    op.drop_table("funding_boundary_tasks")
    op.drop_constraint("ck_funding_payment_paid_basis", "funding_payments", type_="check")
    op.drop_constraint("ck_funding_payment_amount_status", "funding_payments", type_="check")
    op.drop_constraint("ck_funding_payment_status", "funding_payments", type_="check")
    op.drop_column("funding_payments", "reason")
    op.drop_column("funding_payments", "status")
    op.drop_column("funding_payments", "evidence_id")
    op.drop_column("funding_payments", "oracle_px")
    op.alter_column("funding_payments", "amount", nullable=False)
    op.alter_column("funding_payments", "rate", nullable=False)
    op.drop_constraint("ck_positions_closed_at_state", "positions", type_="check")
    op.drop_column("positions", "closed_at")
    op.drop_column("market_quotes", "context_received_at")
    op.drop_column("market_quotes", "oracle_px")
