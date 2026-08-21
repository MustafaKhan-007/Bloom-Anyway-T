"""Founder monthly/annual list prices on membership_plans.

Revision ID: g3p1k2l3m4n5
Revises: f2o0j1k2l3m4
"""
from alembic import op
import sqlalchemy as sa


revision = "g3p1k2l3m4n5"
down_revision = "f2o0j1k2l3m4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("membership_plans") as batch:
        batch.add_column(sa.Column("founder_price_cents", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("founder_annual_price_cents", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("membership_plans") as batch:
        batch.drop_column("founder_annual_price_cents")
        batch.drop_column("founder_price_cents")
