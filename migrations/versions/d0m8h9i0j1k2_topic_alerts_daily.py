"""Topic alert subscriptions + Daily rooms for peer support meetings.

Revision ID: d0m8h9i0j1k2
Revises: c9l7g8h9i0j1
Create Date: 2026-08-20
"""
from alembic import op
import sqlalchemy as sa


revision = "d0m8h9i0j1k2"
down_revision = "c9l7g8h9i0j1"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "support_group_topic_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"),
                  nullable=False),
        sa.Column("circle_id", sa.Integer(),
                  sa.ForeignKey("support_group_circles.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "user_id", "circle_id",
            name="uq_support_topic_alert_user_circle",
        ),
    )
    op.create_index(
        "ix_support_group_topic_alerts_user_id",
        "support_group_topic_alerts", ["user_id"],
    )
    op.create_index(
        "ix_support_group_topic_alerts_circle_id",
        "support_group_topic_alerts", ["circle_id"],
    )


def downgrade():
    op.drop_index(
        "ix_support_group_topic_alerts_circle_id",
        table_name="support_group_topic_alerts",
    )
    op.drop_index(
        "ix_support_group_topic_alerts_user_id",
        table_name="support_group_topic_alerts",
    )
    op.drop_table("support_group_topic_alerts")
