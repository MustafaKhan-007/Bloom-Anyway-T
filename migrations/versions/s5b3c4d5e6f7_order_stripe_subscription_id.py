"""order stripe subscription id

Revision ID: s5b3c4d5e6f7
Revises: r4a2b3c4d5e6
"""
import sqlalchemy as sa
from alembic import op

revision = "s5b3c4d5e6f7"
down_revision = "r4a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("stripe_subscription_id", sa.String(length=80), nullable=True))
        batch.create_index("ix_orders_stripe_subscription_id", ["stripe_subscription_id"])


def downgrade():
    with op.batch_alter_table("orders") as batch:
        batch.drop_index("ix_orders_stripe_subscription_id")
        batch.drop_column("stripe_subscription_id")
