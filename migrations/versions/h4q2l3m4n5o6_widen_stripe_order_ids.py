"""Widen order ids for Stripe Checkout Session ids (cs_live_…).

Revision ID: h4q2l3m4n5o6
Revises: g3p1k2l3m4n5
"""
from alembic import op
import sqlalchemy as sa


revision = "h4q2l3m4n5o6"
down_revision = "g3p1k2l3m4n5"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("orders") as batch:
        batch.alter_column(
            "ls_order_id",
            existing_type=sa.String(length=40),
            type_=sa.String(length=120),
            existing_nullable=False,
        )
        batch.alter_column(
            "ls_variant_id",
            existing_type=sa.String(length=40),
            type_=sa.String(length=80),
            existing_nullable=True,
        )
    with op.batch_alter_table("shop_purchases") as batch:
        batch.alter_column(
            "lemon_squeezy_order_id",
            existing_type=sa.String(length=40),
            type_=sa.String(length=120),
            existing_nullable=False,
        )


def downgrade():
    with op.batch_alter_table("shop_purchases") as batch:
        batch.alter_column(
            "lemon_squeezy_order_id",
            existing_type=sa.String(length=120),
            type_=sa.String(length=40),
            existing_nullable=False,
        )
    with op.batch_alter_table("orders") as batch:
        batch.alter_column(
            "ls_variant_id",
            existing_type=sa.String(length=80),
            type_=sa.String(length=40),
            existing_nullable=True,
        )
        batch.alter_column(
            "ls_order_id",
            existing_type=sa.String(length=120),
            type_=sa.String(length=40),
            existing_nullable=False,
        )
