"""Persist product covers and gallery images in Postgres."""
from alembic import op
import sqlalchemy as sa


revision = "b8k6f7g8h9i0"
down_revision = "a7j5e6f7g8h9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("products") as batch:
        batch.add_column(sa.Column("cover_data", sa.LargeBinary(), nullable=True))
        batch.add_column(sa.Column("cover_mime", sa.String(length=40), nullable=True))

    op.create_table(
        "product_gallery_images",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(),
                  sa.ForeignKey("products.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("filename", sa.String(length=80), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("mime", sa.String(length=40), nullable=False,
                  server_default="image/jpeg"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_product_gallery_images_product_id",
        "product_gallery_images",
        ["product_id"],
    )
    op.create_index(
        "ix_product_gallery_images_product_filename",
        "product_gallery_images",
        ["product_id", "filename"],
        unique=True,
    )


def downgrade():
    op.drop_index("ix_product_gallery_images_product_filename",
                  table_name="product_gallery_images")
    op.drop_index("ix_product_gallery_images_product_id",
                  table_name="product_gallery_images")
    op.drop_table("product_gallery_images")
    with op.batch_alter_table("products") as batch:
        batch.drop_column("cover_mime")
        batch.drop_column("cover_data")
