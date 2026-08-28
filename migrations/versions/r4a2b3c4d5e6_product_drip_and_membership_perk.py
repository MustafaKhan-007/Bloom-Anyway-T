"""Drip-fed product modules + free membership perk on purchase.

Revision ID: r4a2b3c4d5e6
Revises: q3z1a2b3c4d5
"""
import sqlalchemy as sa
from alembic import op


revision = "r4a2b3c4d5e6"
down_revision = "q3z1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("products") as batch:
        batch.add_column(sa.Column("drip_enabled", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))
        batch.add_column(sa.Column("drip_interval_days", sa.Integer(), nullable=False,
                                   server_default="7"))
        batch.add_column(sa.Column("perk_membership_tier", sa.String(length=20),
                                   nullable=True))
        batch.add_column(sa.Column("perk_membership_months", sa.Integer(), nullable=False,
                                   server_default="0"))
    with op.batch_alter_table("product_assets") as batch:
        batch.add_column(sa.Column("module_index", sa.Integer(), nullable=True))
        batch.create_index("ix_product_assets_module_index", ["module_index"])
    with op.batch_alter_table("course_progress") as batch:
        batch.add_column(sa.Column("module_index", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("course_progress") as batch:
        batch.drop_column("module_index")
    with op.batch_alter_table("product_assets") as batch:
        batch.drop_index("ix_product_assets_module_index")
        batch.drop_column("module_index")
    with op.batch_alter_table("products") as batch:
        batch.drop_column("perk_membership_months")
        batch.drop_column("perk_membership_tier")
        batch.drop_column("drip_interval_days")
        batch.drop_column("drip_enabled")
