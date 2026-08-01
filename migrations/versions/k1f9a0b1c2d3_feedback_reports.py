"""Site feedback inbox and forum content reports.

Revision ID: k1f9a0b1c2d3
Revises: j0e8f9a0b1c2
"""
from alembic import op
import sqlalchemy as sa


revision = "k1f9a0b1c2d3"
down_revision = "j0e8f9a0b1c2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "site_feedback",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("stars", sa.Integer(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("page_path", sa.String(length=300), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("contact_email", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("site_feedback", schema=None) as batch_op:
        batch_op.create_index("ix_site_feedback_kind", ["kind"], unique=False)
        batch_op.create_index("ix_site_feedback_status", ["status"], unique=False)
        batch_op.create_index("ix_site_feedback_user_id", ["user_id"], unique=False)

    op.create_table(
        "content_reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("reporter_id", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("auto_hidden", sa.Boolean(), nullable=False),
        sa.Column("auto_reason", sa.String(length=240), nullable=True),
        sa.Column("owner_note", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("content_reports", schema=None) as batch_op:
        batch_op.create_index("ix_content_reports_reporter_id", ["reporter_id"], unique=False)
        batch_op.create_index("ix_content_reports_status", ["status"], unique=False)
        batch_op.create_index("ix_content_reports_target_id", ["target_id"], unique=False)


def downgrade():
    with op.batch_alter_table("content_reports", schema=None) as batch_op:
        batch_op.drop_index("ix_content_reports_target_id")
        batch_op.drop_index("ix_content_reports_status")
        batch_op.drop_index("ix_content_reports_reporter_id")
    op.drop_table("content_reports")
    with op.batch_alter_table("site_feedback", schema=None) as batch_op:
        batch_op.drop_index("ix_site_feedback_user_id")
        batch_op.drop_index("ix_site_feedback_status")
        batch_op.drop_index("ix_site_feedback_kind")
    op.drop_table("site_feedback")
