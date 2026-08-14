"""View-only Studio owner flag.

Revision ID: w3f1a2b3c4d5
Revises: v2e0f1a2b3c4
"""
from alembic import op
import sqlalchemy as sa


revision = "w3f1a2b3c4d5"
down_revision = "v2e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column(
            "admin_readonly", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.drop_column("admin_readonly")
