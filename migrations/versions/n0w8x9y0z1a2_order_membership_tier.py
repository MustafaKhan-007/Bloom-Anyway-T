"""Store membership_tier on orders; unique Stripe price ids on plans.

Revision ID: n0w8x9y0z1a2
Revises: m9v7w8x9y0z1
"""
import sqlalchemy as sa
from alembic import op


revision = "n0w8x9y0z1a2"
down_revision = "m9v7w8x9y0z1"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("orders") as batch:
        batch.add_column(sa.Column("membership_tier", sa.String(20), nullable=True))
        batch.create_index("ix_orders_membership_tier", ["membership_tier"])

    # Empty strings break UNIQUE (SQLite treats '' as a real value).
    op.execute(
        "UPDATE membership_plans SET stripe_price_id = NULL "
        "WHERE stripe_price_id IS NOT NULL AND TRIM(stripe_price_id) = ''"
    )
    op.execute(
        "UPDATE membership_plans SET stripe_price_id_annual = NULL "
        "WHERE stripe_price_id_annual IS NOT NULL AND TRIM(stripe_price_id_annual) = ''"
    )
    op.execute(
        "UPDATE membership_plans SET ls_variant_id = NULL "
        "WHERE ls_variant_id IS NOT NULL AND TRIM(ls_variant_id) = ''"
    )

    # Backfill order tier from MembershipPlan price ids (price → plan only).
    conn = op.get_bind()
    plans = conn.execute(
        sa.text(
            "SELECT tier, stripe_price_id, stripe_price_id_annual, ls_variant_id "
            "FROM membership_plans"
        )
    ).fetchall()
    price_to_tier = {}
    for tier, monthly, annual, legacy in plans:
        if tier not in ("healing", "creator", "full_bloom"):
            continue
        for raw in (monthly, annual, legacy):
            key = (raw or "").strip()
            if key and key not in price_to_tier:
                price_to_tier[key] = tier
    for price_id, tier in price_to_tier.items():
        conn.execute(
            sa.text(
                "UPDATE orders SET membership_tier = :tier "
                "WHERE status = 'paid' AND membership_tier IS NULL "
                "AND ls_variant_id = :pid"
            ),
            {"tier": tier, "pid": price_id},
        )

    with op.batch_alter_table("membership_plans") as batch:
        batch.create_index(
            "uq_membership_plans_stripe_price_id",
            ["stripe_price_id"],
            unique=True,
        )
        batch.create_index(
            "uq_membership_plans_stripe_price_id_annual",
            ["stripe_price_id_annual"],
            unique=True,
        )


def downgrade():
    with op.batch_alter_table("membership_plans") as batch:
        batch.drop_index("uq_membership_plans_stripe_price_id_annual")
        batch.drop_index("uq_membership_plans_stripe_price_id")
    with op.batch_alter_table("orders") as batch:
        batch.drop_index("ix_orders_membership_tier")
        batch.drop_column("membership_tier")
