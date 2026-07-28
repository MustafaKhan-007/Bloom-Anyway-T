"""Add optional animated avatar payload for profile-page playback.

Revision ID: j0e8f9a0b1c2
Revises: i9d7e8f9a0b1
"""
from alembic import op
import sqlalchemy as sa


revision = "j0e8f9a0b1c2"
down_revision = "i9d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("avatar_anim_data", sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column("avatar_anim_mime", sa.String(length=40), nullable=True))


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("avatar_anim_mime")
        batch_op.drop_column("avatar_anim_data")
