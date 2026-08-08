"""Courses track fields, Dodo product ids, visit attribution.

Revision ID: p6e4f5a6b7c8
Revises: o5d3e4f5a6b7
"""
from alembic import op
import sqlalchemy as sa


revision = "p6e4f5a6b7c8"
down_revision = "o5d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("products") as batch:
        batch.add_column(sa.Column("track", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("meta_line", sa.String(length=200), nullable=True))
        batch.add_column(sa.Column("category_label", sa.String(length=80), nullable=True))
        batch.add_column(sa.Column("dodo_product_id", sa.String(length=80), nullable=True))
        batch.create_index("ix_products_track", ["track"])
        batch.create_index("ix_products_dodo_product_id", ["dodo_product_id"])

    with op.batch_alter_table("membership_plans") as batch:
        batch.add_column(sa.Column("dodo_product_id", sa.String(length=80), nullable=True))
        batch.create_index("ix_membership_plans_dodo_product_id", ["dodo_product_id"])

    op.create_table(
        "visit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("path", sa.String(length=300), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("referrer", sa.String(length=500), nullable=True),
        sa.Column("utm_source", sa.String(length=120), nullable=True),
        sa.Column("utm_medium", sa.String(length=120), nullable=True),
        sa.Column("utm_campaign", sa.String(length=160), nullable=True),
        sa.Column("session_key", sa.String(length=64), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index("ix_visit_events_created_at", "visit_events", ["created_at"])
    op.create_index("ix_visit_events_source", "visit_events", ["source"])
    op.create_index("ix_visit_events_user_id", "visit_events", ["user_id"])


def downgrade():
    op.drop_index("ix_visit_events_user_id", table_name="visit_events")
    op.drop_index("ix_visit_events_source", table_name="visit_events")
    op.drop_index("ix_visit_events_created_at", table_name="visit_events")
    op.drop_table("visit_events")
    with op.batch_alter_table("membership_plans") as batch:
        batch.drop_index("ix_membership_plans_dodo_product_id")
        batch.drop_column("dodo_product_id")
    with op.batch_alter_table("products") as batch:
        batch.drop_index("ix_products_dodo_product_id")
        batch.drop_index("ix_products_track")
        batch.drop_column("dodo_product_id")
        batch.drop_column("category_label")
        batch.drop_column("meta_line")
        batch.drop_column("track")
