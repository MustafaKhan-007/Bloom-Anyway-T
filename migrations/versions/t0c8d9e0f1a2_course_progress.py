"""On-site course reader progress + widen product_assets.kind.

Revision ID: t0c8d9e0f1a2
Revises: s9b7c8d9e0f1
"""
from alembic import op
import sqlalchemy as sa


revision = "t0c8d9e0f1a2"
down_revision = "s9b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("product_assets") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.String(length=10),
            type_=sa.String(length=20),
            existing_nullable=False,
        )

    op.create_table(
        "course_progress",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("shop_purchase_id", sa.Integer(),
                  sa.ForeignKey("shop_purchases.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id")),
        sa.Column("current_page", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("total_pages", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table("course_progress") as batch:
        batch.create_index("ix_course_progress_user_id", ["user_id"])
        batch.create_index("ix_course_progress_shop_purchase_id", ["shop_purchase_id"],
                           unique=True)
        batch.create_index("ix_course_progress_product_id", ["product_id"])


def downgrade():
    op.drop_table("course_progress")
    with op.batch_alter_table("product_assets") as batch:
        batch.alter_column(
            "kind",
            existing_type=sa.String(length=20),
            type_=sa.String(length=10),
            existing_nullable=False,
        )
