"""Rename Dodo product id columns to Stripe price ids."""
from alembic import op
import sqlalchemy as sa


revision = "z6i4d5e6f7g8"
down_revision = "y5h3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("products") as batch:
        batch.alter_column(
            "dodo_product_id",
            new_column_name="stripe_price_id",
            existing_type=sa.String(length=80),
            existing_nullable=True,
        )
    with op.batch_alter_table("membership_plans") as batch:
        batch.alter_column(
            "dodo_product_id",
            new_column_name="stripe_price_id",
            existing_type=sa.String(length=80),
            existing_nullable=True,
        )
        batch.alter_column(
            "dodo_product_id_annual",
            new_column_name="stripe_price_id_annual",
            existing_type=sa.String(length=80),
            existing_nullable=True,
        )


def downgrade():
    with op.batch_alter_table("membership_plans") as batch:
        batch.alter_column(
            "stripe_price_id_annual",
            new_column_name="dodo_product_id_annual",
            existing_type=sa.String(length=80),
            existing_nullable=True,
        )
        batch.alter_column(
            "stripe_price_id",
            new_column_name="dodo_product_id",
            existing_type=sa.String(length=80),
            existing_nullable=True,
        )
    with op.batch_alter_table("products") as batch:
        batch.alter_column(
            "stripe_price_id",
            new_column_name="dodo_product_id",
            existing_type=sa.String(length=80),
            existing_nullable=True,
        )
