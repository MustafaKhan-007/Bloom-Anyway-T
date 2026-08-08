"""Annual membership price + Dodo product id.

Revision ID: q7f5a6b7c8d9
Revises: p6e4f5a6b7c8
"""
from alembic import op
import sqlalchemy as sa


revision = "q7f5a6b7c8d9"
down_revision = "p6e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("membership_plans") as batch:
        batch.add_column(sa.Column("annual_price_cents", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("dodo_product_id_annual", sa.String(length=80), nullable=True))
        batch.create_index("ix_membership_plans_dodo_product_id_annual",
                           ["dodo_product_id_annual"])


def downgrade():
    with op.batch_alter_table("membership_plans") as batch:
        batch.drop_index("ix_membership_plans_dodo_product_id_annual")
        batch.drop_column("dodo_product_id_annual")
        batch.drop_column("annual_price_cents")
