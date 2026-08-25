"""Coach availability windows + 1:1 coaching intake questionnaires.

Revision ID: j6s4n5o6p7q8
Revises: i5r3m4n5o6p7
"""
from alembic import op
import sqlalchemy as sa


revision = "j6s4n5o6p7q8"
down_revision = "i5r3m4n5o6p7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "coach_availability",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("coach", sa.String(length=20), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("start_minute", sa.Integer(), nullable=False),
        sa.Column("end_minute", sa.Integer(), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("coach_availability") as batch:
        batch.create_index("ix_coach_availability_coach", ["coach"])

    op.create_table(
        "coaching_intakes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("coach", sa.String(length=20), nullable=False),
        sa.Column("answers_json", sa.Text(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("meeting_id", sa.Integer(), nullable=True),
        sa.Column("stripe_session_id", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["meeting_id"], ["support_group_meetings.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("coaching_intakes") as batch:
        batch.create_index("ix_coaching_intakes_user_id", ["user_id"])
        batch.create_index("ix_coaching_intakes_coach", ["coach"])
        batch.create_index("ix_coaching_intakes_status", ["status"])
        batch.create_index("ix_coaching_intakes_meeting_id", ["meeting_id"])


def downgrade():
    with op.batch_alter_table("coaching_intakes") as batch:
        batch.drop_index("ix_coaching_intakes_meeting_id")
        batch.drop_index("ix_coaching_intakes_status")
        batch.drop_index("ix_coaching_intakes_coach")
        batch.drop_index("ix_coaching_intakes_user_id")
    op.drop_table("coaching_intakes")
    with op.batch_alter_table("coach_availability") as batch:
        batch.drop_index("ix_coach_availability_coach")
    op.drop_table("coach_availability")
