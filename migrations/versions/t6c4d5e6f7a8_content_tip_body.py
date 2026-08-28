"""content hub tips: written body, optional video

Revision ID: t6c4d5e6f7a8
Revises: s5b3c4d5e6f7
"""
import sqlalchemy as sa
from alembic import op

revision = "t6c4d5e6f7a8"
down_revision = "s5b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("videos") as batch:
        batch.add_column(sa.Column("body", sa.Text(), nullable=True))
        # A tip without a video has no mime type.
        batch.alter_column("mime", existing_type=sa.String(length=120), nullable=True)


def downgrade():
    op.execute("UPDATE videos SET mime = '' WHERE mime IS NULL")
    with op.batch_alter_table("videos") as batch:
        batch.alter_column("mime", existing_type=sa.String(length=120), nullable=False)
        batch.drop_column("body")
