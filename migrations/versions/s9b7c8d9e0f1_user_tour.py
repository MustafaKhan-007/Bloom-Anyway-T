"""Product tour completion timestamp on users.

Revision ID: s9b7c8d9e0f1
Revises: r8a6b7c8d9e0
"""
from alembic import op
import sqlalchemy as sa


revision = "s9b7c8d9e0f1"
down_revision = "r8a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("tour_completed_at", sa.DateTime(), nullable=True))
    # Existing accounts skip the tour; only new signups see it.
    op.execute(sa.text("UPDATE users SET tour_completed_at = CURRENT_TIMESTAMP"))


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.drop_column("tour_completed_at")
