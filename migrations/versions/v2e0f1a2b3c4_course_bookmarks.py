"""Bookmarked pages on course reading progress.

Revision ID: v2e0f1a2b3c4
Revises: u1d9e0f1a2b3
"""
from alembic import op
import sqlalchemy as sa


revision = "v2e0f1a2b3c4"
down_revision = "u1d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("course_progress") as batch:
        batch.add_column(sa.Column("bookmarks_json", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("course_progress") as batch:
        batch.drop_column("bookmarks_json")
