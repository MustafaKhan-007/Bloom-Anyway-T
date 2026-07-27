"""Add looking_for intent column on forum posts.

Revision ID: h8c6d7e8f9a0
Revises: g7b5c6d7e8f9
"""
from alembic import op
import sqlalchemy as sa


revision = "h8c6d7e8f9a0"
down_revision = "g7b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("forum_posts", schema=None) as batch_op:
        batch_op.add_column(sa.Column("looking_for", sa.String(length=40), nullable=True))
        batch_op.create_index("ix_forum_posts_looking_for", ["looking_for"], unique=False)


def downgrade():
    with op.batch_alter_table("forum_posts", schema=None) as batch_op:
        batch_op.drop_index("ix_forum_posts_looking_for")
        batch_op.drop_column("looking_for")
