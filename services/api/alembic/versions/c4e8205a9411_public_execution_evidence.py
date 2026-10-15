"""Add immutable execution timestamps and ordering references.

Revision ID: c4e8205a9411
Revises: b35a4d9c12ef
Create Date: 2026-10-15 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "c4e8205a9411"
down_revision = "b35a4d9c12ef"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fills", sa.Column("executed_at", sa.DateTime(timezone=True)))
    op.add_column("fills", sa.Column("ordinal", sa.Integer()))
    op.add_column("orders", sa.Column("event_sequence", sa.BigInteger()))
    op.add_column("orders", sa.Column("quote_set_id", sa.String(length=36)))
    op.create_foreign_key(
        "fk_orders_quote_set_id_quote_sets",
        "orders",
        "quote_sets",
        ["quote_set_id"],
        ["id"],
    )
    op.create_index("ix_orders_event_sequence", "orders", ["event_sequence"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER decision_rounds_append_only ON decision_rounds")
        op.execute(
            """
            CREATE FUNCTION protect_decision_round_pin() RETURNS trigger
            LANGUAGE plpgsql AS $$
            BEGIN
                IF TG_OP = 'DELETE' THEN
                    RAISE EXCEPTION 'decision round evidence is append-only';
                END IF;
                IF (to_jsonb(NEW) - 'execution_quote_set_id') IS DISTINCT FROM
                   (to_jsonb(OLD) - 'execution_quote_set_id') THEN
                    RAISE EXCEPTION 'decision round evidence is append-only';
                END IF;
                IF OLD.execution_quote_set_id IS NOT NULL AND
                   NEW.execution_quote_set_id IS DISTINCT FROM OLD.execution_quote_set_id THEN
                    RAISE EXCEPTION 'decision round quote set pin is immutable';
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
        op.execute(
            "CREATE TRIGGER decision_rounds_append_only BEFORE UPDATE OR DELETE "
            "ON decision_rounds FOR EACH ROW EXECUTE FUNCTION protect_decision_round_pin()"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER decision_rounds_append_only ON decision_rounds")
        op.execute("DROP FUNCTION protect_decision_round_pin()")
        op.execute(
            "CREATE TRIGGER decision_rounds_append_only BEFORE UPDATE OR DELETE "
            "ON decision_rounds FOR EACH ROW EXECUTE FUNCTION reject_evidence_mutation()"
        )
    op.drop_index("ix_orders_event_sequence", table_name="orders")
    op.drop_constraint("fk_orders_quote_set_id_quote_sets", "orders", type_="foreignkey")
    op.drop_column("orders", "quote_set_id")
    op.drop_column("orders", "event_sequence")
    op.drop_column("fills", "ordinal")
    op.drop_column("fills", "executed_at")
