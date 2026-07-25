"""Migrate purchases -> shop_purchases for external shop fulfillment.

Revision ID: e5f2a3b4c5d6
Revises: d4e1f2a3b5c6
"""
from alembic import op
import sqlalchemy as sa


revision = "e5f2a3b4c5d6"
down_revision = "d4e1f2a3b5c6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "shop_purchases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lemon_squeezy_order_id", sa.String(length=40), nullable=False),
        sa.Column("customer_email", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("product_name", sa.String(length=200), nullable=False),
        sa.Column("product_id", sa.String(length=80), nullable=True),
        sa.Column("variant_id", sa.String(length=80), nullable=True),
        sa.Column("download_url", sa.String(length=1000), nullable=True),
        sa.Column("file_key", sa.String(length=255), nullable=True),
        sa.Column("purchased_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.UniqueConstraint("lemon_squeezy_order_id"),
    )
    op.create_index("ix_shop_purchases_customer_email", "shop_purchases", ["customer_email"])
    op.create_index("ix_shop_purchases_user_id", "shop_purchases", ["user_id"])
    op.create_index("ix_shop_purchases_file_key", "shop_purchases", ["file_key"])

    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if "purchases" in inspector.get_table_names():
        # Map legacy Purchase rows: paid+user -> linked, paid+no user -> pending_link,
        # refunded stays refunded.
        op.execute(
            sa.text(
                """
                INSERT INTO shop_purchases (
                    lemon_squeezy_order_id, customer_email, user_id, product_name,
                    product_id, variant_id, download_url, file_key, purchased_at, status
                )
                SELECT
                    order_id,
                    email,
                    user_id,
                    CASE WHEN product_name = '' OR product_name IS NULL
                         THEN 'Shop purchase' ELSE product_name END,
                    product_id,
                    variant_id,
                    NULL,
                    NULL,
                    created_at,
                    CASE
                        WHEN status = 'refunded' THEN 'refunded'
                        WHEN user_id IS NOT NULL THEN 'linked'
                        ELSE 'pending_link'
                    END
                FROM purchases
                """
            )
        )
        op.drop_table("purchases")


def downgrade():
    op.create_table(
        "purchases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("product_id", sa.String(length=40), nullable=True),
        sa.Column("variant_id", sa.String(length=40), nullable=True),
        sa.Column("product_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("order_id", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="paid"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id"),
    )
    with op.batch_alter_table("purchases", schema=None) as batch_op:
        batch_op.create_index("ix_purchases_email", ["email"])
        batch_op.create_index("ix_purchases_user_id", ["user_id"])
        batch_op.create_index("ix_purchases_variant_id", ["variant_id"])

    op.execute(
        sa.text(
            """
            INSERT INTO purchases (
                order_id, email, user_id, product_name, product_id, variant_id,
                status, created_at
            )
            SELECT
                lemon_squeezy_order_id,
                customer_email,
                user_id,
                product_name,
                product_id,
                variant_id,
                CASE
                    WHEN status = 'refunded' THEN 'refunded'
                    ELSE 'paid'
                END,
                purchased_at
            FROM shop_purchases
            """
        )
    )

    op.drop_index("ix_shop_purchases_file_key", table_name="shop_purchases")
    op.drop_index("ix_shop_purchases_user_id", table_name="shop_purchases")
    op.drop_index("ix_shop_purchases_customer_email", table_name="shop_purchases")
    op.drop_table("shop_purchases")
