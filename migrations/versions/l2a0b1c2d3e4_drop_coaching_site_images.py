"""Drop coaching requests; add site image uploads.

Revision ID: l2a0b1c2d3e4
Revises: k1f9a0b1c2d3
"""
from alembic import op
import sqlalchemy as sa


revision = "l2a0b1c2d3e4"
down_revision = "k1f9a0b1c2d3"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_table("coaching_requests")
    op.create_table(
        "site_images",
        sa.Column("key", sa.String(length=40), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("mime", sa.String(length=40), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade():
    op.drop_table("site_images")
    op.create_table(
        "coaching_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("preferred_times", sa.String(length=300), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_coaching_requests_user_id", "coaching_requests", ["user_id"])
