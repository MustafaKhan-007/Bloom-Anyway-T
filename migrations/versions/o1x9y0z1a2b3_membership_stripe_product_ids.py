"""Add Stripe product ids on membership plans.

Revision ID: o1x9y0z1a2b3
Revises: n0w8x9y0z1a2
"""
import sqlalchemy as sa
from alembic import op


revision = "o1x9y0z1a2b3"
down_revision = "n0w8x9y0z1a2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("membership_plans") as batch:
        batch.add_column(sa.Column("stripe_product_id", sa.String(80), nullable=True))
        batch.add_column(sa.Column("stripe_product_id_annual", sa.String(80), nullable=True))
        batch.create_index(
            "uq_membership_plans_stripe_product_id",
            ["stripe_product_id"],
            unique=True,
        )
        batch.create_index(
            "uq_membership_plans_stripe_product_id_annual",
            ["stripe_product_id_annual"],
            unique=True,
        )


def downgrade():
    with op.batch_alter_table("membership_plans") as batch:
        batch.drop_index("uq_membership_plans_stripe_product_id_annual")
        batch.drop_index("uq_membership_plans_stripe_product_id")
        batch.drop_column("stripe_product_id_annual")
        batch.drop_column("stripe_product_id")
