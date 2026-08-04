"""Add support-group applications and meetings.

Revision ID: m3b1c2d3e4f5
Revises: l2a0b1c2d3e4
"""
from alembic import op
import sqlalchemy as sa


revision = "m3b1c2d3e4f5"
down_revision = "l2a0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "support_group_meetings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("zoom_url", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("booked_notified_at", sa.DateTime(), nullable=True),
        sa.Column("reminded_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("support_group_meetings") as batch:
        batch.create_index(
            batch.f("ix_support_group_meetings_status"), ["status"], unique=False,
        )

    op.create_table(
        "support_group_applications",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["support_group_meetings.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("support_group_applications") as batch:
        batch.create_index(
            batch.f("ix_support_group_applications_user_id"), ["user_id"], unique=False,
        )
        batch.create_index(
            batch.f("ix_support_group_applications_meeting_id"),
            ["meeting_id"], unique=False,
        )
        batch.create_index(
            batch.f("ix_support_group_applications_status"), ["status"], unique=False,
        )


def downgrade():
    with op.batch_alter_table("support_group_applications") as batch:
        batch.drop_index(batch.f("ix_support_group_applications_status"))
        batch.drop_index(batch.f("ix_support_group_applications_meeting_id"))
        batch.drop_index(batch.f("ix_support_group_applications_user_id"))
    op.drop_table("support_group_applications")
    with op.batch_alter_table("support_group_meetings") as batch:
        batch.drop_index(batch.f("ix_support_group_meetings_status"))
    op.drop_table("support_group_meetings")
