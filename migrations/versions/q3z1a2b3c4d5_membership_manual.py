"""Add membership_manual so Studio tier changes stick over Stripe sync.

Revision ID: q3z1a2b3c4d5
Revises: p2y0z1a2b3c4
"""
import sqlalchemy as sa
from alembic import op


revision = "q3z1a2b3c4d5"
down_revision = "p2y0z1a2b3c4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("membership_manual", sa.String(length=20),
                                   nullable=True))
        batch.add_column(sa.Column("membership_manual_at", sa.DateTime(),
                                   nullable=True))


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.drop_column("membership_manual_at")
        batch.drop_column("membership_manual")
