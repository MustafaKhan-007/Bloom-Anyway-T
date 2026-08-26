"""Challenge waitlist table + Creator/Full Bloom showcase cap 5.

Revision ID: l8u6v7w8x9y0
Revises: k7t5u6v7w8x9
"""
import json

import sqlalchemy as sa
from alembic import op


revision = "l8u6v7w8x9y0"
down_revision = "k7t5u6v7w8x9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "challenge_waitlist",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_challenge_waitlist_email",
        "challenge_waitlist",
        ["email"],
        unique=True,
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, tier, features_json FROM membership_plans")
    ).fetchall()
    for row in rows:
        plan_id, tier, raw = row[0], row[1], row[2]
        if tier not in ("creator", "full_bloom"):
            continue
        data = {}
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    data = parsed
            except (TypeError, ValueError):
                data = {}
        if int(data.get("showcase_listings") or 0) == 15:
            data["showcase_listings"] = 5
            bind.execute(
                sa.text(
                    "UPDATE membership_plans SET features_json = :fj WHERE id = :id"
                ),
                {"fj": json.dumps(data), "id": plan_id},
            )


def downgrade():
    op.drop_index("ix_challenge_waitlist_email", table_name="challenge_waitlist")
    op.drop_table("challenge_waitlist")
