"""owners-only test products

Revision ID: x0a8b9c0d1e2
Revises: w9f7a8b9c0d1
"""
import sqlalchemy as sa
from alembic import op

revision = "x0a8b9c0d1e2"
down_revision = "w9f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("products") as batch:
        batch.add_column(sa.Column("test_mode", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))
        batch.create_index("ix_products_test_mode", ["test_mode"])


def downgrade():
    with op.batch_alter_table("products") as batch:
        batch.drop_index("ix_products_test_mode")
        batch.drop_column("test_mode")
