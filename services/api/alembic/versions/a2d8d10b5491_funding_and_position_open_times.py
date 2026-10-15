"""Ensure funding idempotency and opened-at fields exist.

Revision ID: a2d8d10b5491
Revises: 89d414f86f12
"""

import sqlalchemy as sa
from alembic import op

revision = "a2d8d10b5491"
down_revision = "89d414f86f12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    position_columns = {column["name"] for column in sa.inspect(bind).get_columns("positions")}
    if "opened_at" not in position_columns:
        op.add_column(
            "positions",
            sa.Column(
                "opened_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )
    funding_constraints = {
        item["name"] for item in sa.inspect(bind).get_unique_constraints("funding_payments")
    }
    if "uq_funding_payment_position_event" not in funding_constraints:
        op.create_unique_constraint(
            "uq_funding_payment_position_event",
            "funding_payments",
            ["position_id", "event_at"],
        )


def downgrade() -> None:
    op.drop_constraint(
        "uq_funding_payment_position_event", "funding_payments", type_="unique"
    )
    op.drop_column("positions", "opened_at")
