"""stand-in accounts owners can hand-make in Studio

Revision ID: w9f7a8b9c0d1
Revises: v8e6f7a8b9c0
"""
import sqlalchemy as sa
from alembic import op

revision = "w9f7a8b9c0d1"
down_revision = "v8e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("is_demo", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))
        batch.create_index("ix_users_is_demo", ["is_demo"])


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_is_demo")
        batch.drop_column("is_demo")
