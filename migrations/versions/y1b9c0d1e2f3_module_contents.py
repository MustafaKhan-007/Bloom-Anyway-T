"""course modules hold many videos, documents and written extracts

Files now stream to the media disk (``disk_name``) instead of into Postgres,
and a written extract keeps its words in ``body`` with no file at all. ``data``
becomes nullable so those two can exist; rows uploaded before this keep their
blob and still open.

Revision ID: y1b9c0d1e2f3
Revises: x0a8b9c0d1e2
"""
import sqlalchemy as sa
from alembic import op

revision = "y1b9c0d1e2f3"
down_revision = "x0a8b9c0d1e2"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("product_assets") as batch:
        batch.add_column(sa.Column("disk_name", sa.String(length=120)))
        batch.add_column(sa.Column("body", sa.Text()))
        batch.alter_column("data", existing_type=sa.LargeBinary(),
                           nullable=True)


def downgrade():
    # Anything living on disk or written inline has no blob to put back, so it
    # would violate the old NOT NULL. Drop those rows rather than fail halfway.
    op.execute("DELETE FROM product_assets WHERE data IS NULL")
    with op.batch_alter_table("product_assets") as batch:
        batch.alter_column("data", existing_type=sa.LargeBinary(),
                           nullable=False)
        batch.drop_column("body")
        batch.drop_column("disk_name")
