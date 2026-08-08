"""Named support-group circles (categories) + FK on apps/meetings.

Revision ID: o5d3e4f5a6b7
Revises: n4c2d3e4f5a6
"""
from alembic import op
import sqlalchemy as sa


revision = "o5d3e4f5a6b7"
down_revision = "n4c2d3e4f5a6"
branch_labels = None
depends_on = None

_SEED = (
    ("divorce-recovery", "healing", "Divorce Recovery",
     "Process endings, paperwork, and the quiet after — with women who get it.",
     12, "Mondays, 8pm", "heart", 10),
    ("co-parenting", "healing", "Co-Parenting Circle",
     "Navigate shared parenting, boundaries, and hard conversations with care.",
     12, "Tuesdays, 7pm", "people", 20),
    ("starting-over", "healing", "Starting Over",
     "Rebuild identity, routines, and confidence when life looks nothing like before.",
     12, "Wednesdays, 8pm", "sun", 30),
    ("grief-loss", "healing", "Grief & Loss",
     "Hold space for what was lost — without having to rush toward fine.",
     12, "Thursdays, 7pm", "candle", 40),
    ("new-creators", "building", "New Creators Circle",
     "Launch your first posts, offers, and habits without spinning alone.",
     10, "Mondays, 7pm", "plant", 50),
    ("digital-products", "building", "Digital Product Builders",
     "Ship guides, templates, and downloads with peers who understand the messy middle.",
     10, "Tuesdays, 8pm", "box", 60),
    ("scaling-up", "building", "Scaling Up",
     "Systems, launches, and sustainable growth when ready to level up.",
     10, "Wednesdays, 7pm", "arrow", 70),
    ("money-investing", "building", "Money & Investing",
     "Normalize talking numbers, pricing, and building wealth on your terms.",
     10, "Thursdays, 8pm", "wallet", 80),
)


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    return sa.inspect(bind).has_table(name)


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns(table)}
    return column in cols


def upgrade():
    # Postgres rejects boolean DEFAULT 1 — use sa.true() (portable).
    if not _has_table("support_group_circles"):
        op.create_table(
            "support_group_circles",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("slug", sa.String(length=60), nullable=False),
            sa.Column("track", sa.String(length=20), nullable=False),
            sa.Column("title", sa.String(length=120), nullable=False),
            sa.Column("blurb", sa.String(length=400), nullable=False),
            sa.Column("capacity", sa.Integer(), nullable=False),
            sa.Column("meets_label", sa.String(length=80), nullable=False),
            sa.Column("icon", sa.String(length=40), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
        op.create_index(
            "ix_support_group_circles_slug", "support_group_circles", ["slug"],
            unique=True,
        )
        op.create_index(
            "ix_support_group_circles_track", "support_group_circles", ["track"],
        )

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
    conn = op.get_bind()
    existing = {
        row[0]
        for row in conn.execute(sa.text("SELECT slug FROM support_group_circles")).fetchall()
    }
    rows = [
        {
            "slug": s, "track": t, "title": title, "blurb": blurb,
            "capacity": cap, "meets_label": meets, "icon": icon,
            "sort_order": order, "active": True,
        }
        for s, t, title, blurb, cap, meets, icon, order in _SEED
        if s not in existing
    ]
    if rows:
        op.bulk_insert(circles, rows)

    if _has_table("support_group_applications") and not _has_column(
            "support_group_applications", "circle_id"):
        with op.batch_alter_table("support_group_applications") as batch:
            batch.add_column(sa.Column("circle_id", sa.Integer(), nullable=True))
            batch.create_index(
                "ix_support_group_applications_circle_id", ["circle_id"],
            )
            batch.create_foreign_key(
                "fk_sg_app_circle", "support_group_circles",
                ["circle_id"], ["id"],
            )

    if _has_table("support_group_meetings") and not _has_column(
            "support_group_meetings", "circle_id"):
        with op.batch_alter_table("support_group_meetings") as batch:
            batch.add_column(sa.Column("circle_id", sa.Integer(), nullable=True))
            batch.create_index(
                "ix_support_group_meetings_circle_id", ["circle_id"],
            )
            batch.create_foreign_key(
                "fk_sg_meeting_circle", "support_group_circles",
                ["circle_id"], ["id"],
            )

    # Attach legacy rows to the first healing circle so nothing is orphaned.
    first = conn.execute(
        sa.text("SELECT id FROM support_group_circles ORDER BY sort_order ASC LIMIT 1")
    ).scalar()
    if first is not None:
        conn.execute(
            sa.text(
                "UPDATE support_group_applications SET circle_id = :cid "
                "WHERE circle_id IS NULL"
            ),
            {"cid": first},
        )
        conn.execute(
            sa.text(
                "UPDATE support_group_meetings SET circle_id = :cid "
                "WHERE circle_id IS NULL"
            ),
            {"cid": first},
        )


def downgrade():
    with op.batch_alter_table("support_group_meetings") as batch:
        batch.drop_constraint("fk_sg_meeting_circle", type_="foreignkey")
        batch.drop_index("ix_support_group_meetings_circle_id")
        batch.drop_column("circle_id")
    with op.batch_alter_table("support_group_applications") as batch:
        batch.drop_constraint("fk_sg_app_circle", type_="foreignkey")
        batch.drop_index("ix_support_group_applications_circle_id")
        batch.drop_column("circle_id")
    op.drop_index("ix_support_group_circles_track", table_name="support_group_circles")
    op.drop_index("ix_support_group_circles_slug", table_name="support_group_circles")
    op.drop_table("support_group_circles")
