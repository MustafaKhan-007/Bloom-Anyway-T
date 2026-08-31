"""Peer-led support meetings: kind + scheduled_by_user_id; meeting cap 8."""
from alembic import op
import sqlalchemy as sa


revision = "c9l7g8h9i0j1"
down_revision = "b8k6f7g8h9i0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("support_group_meetings") as batch:
        batch.add_column(sa.Column(
            "kind", sa.String(length=20), nullable=False, server_default="peer",
        ))
        batch.add_column(sa.Column(
            "scheduled_by_user_id", sa.Integer(),
            # Named on purpose: SQLite has no ALTER, so batch mode rebuilds the
            # table and refuses to copy across a constraint it can't name.
            sa.ForeignKey("users.id",
                          name="fk_support_group_meetings_scheduled_by_user_id"),
            nullable=True,
        ))
        batch.create_index(
            "ix_support_group_meetings_kind", ["kind"],
        )
        batch.create_index(
            "ix_support_group_meetings_scheduled_by_user_id",
            ["scheduled_by_user_id"],
        )

    # Peer sessions are capped at 8 seats.
    op.execute(
        "UPDATE support_group_circles SET capacity = 8 WHERE capacity > 8"
    )
    op.execute(
        "UPDATE support_group_meetings SET capacity = 8 "
        "WHERE status IN ('draft', 'scheduled') AND capacity > 8"
    )
    # Existing admin-formed meetings were facilitator-style seating.
    op.execute(
        "UPDATE support_group_meetings SET kind = 'facilitator' "
        "WHERE scheduled_by_user_id IS NULL AND status IN "
        "('draft', 'scheduled', 'completed', 'cancelled')"
    )


def downgrade():
    with op.batch_alter_table("support_group_meetings") as batch:
        batch.drop_index("ix_support_group_meetings_scheduled_by_user_id")
        batch.drop_index("ix_support_group_meetings_kind")
        batch.drop_column("scheduled_by_user_id")
        batch.drop_column("kind")
