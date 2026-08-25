"""Add Custom peer circles (Healing + Creator) and ensure missing seed rows.

Revision ID: i5r3m4n5o6p7
Revises: h4q2l3m4n5o6
"""
from alembic import op
import sqlalchemy as sa


revision = "i5r3m4n5o6p7"
down_revision = "h4q2l3m4n5o6"
branch_labels = None
depends_on = None

_CUSTOM = (
    ("custom-healing", "healing", "Custom",
     "Name your own Healing peer topic when you schedule — whatever you need to talk through.",
     8, "Peer-scheduled", "spark", 90),
    ("custom-building", "building", "Custom",
     "Name your own Creator accountability topic when you schedule — your call.",
     8, "Peer-scheduled", "spark", 100),
)


def upgrade():
    conn = op.get_bind()
    circles = sa.table(
        "support_group_circles",
        sa.column("slug", sa.String),
        sa.column("track", sa.String),
        sa.column("title", sa.String),
        sa.column("blurb", sa.String),
        sa.column("capacity", sa.Integer),
        sa.column("meets_label", sa.String),
        sa.column("icon", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("active", sa.Boolean),
    )
    existing = {
        row[0]
        for row in conn.execute(sa.text("SELECT slug FROM support_group_circles")).fetchall()
    }
    for slug, track, title, blurb, cap, meets, icon, sort_order in _CUSTOM:
        if slug in existing:
            continue
        conn.execute(
            circles.insert().values(
                slug=slug,
                track=track,
                title=title,
                blurb=blurb,
                capacity=cap,
                meets_label=meets,
                icon=icon,
                sort_order=sort_order,
                active=True,
            )
        )


def downgrade():
    op.execute(
        "DELETE FROM support_group_circles "
        "WHERE slug IN ('custom-healing', 'custom-building')"
    )
