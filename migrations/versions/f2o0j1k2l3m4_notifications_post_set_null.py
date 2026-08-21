"""Notifications SET NULL when a forum post is deleted.

Revision ID: f2o0j1k2l3m4
Revises: e1n9i0j1k2l3
"""
from alembic import op
import sqlalchemy as sa


revision = "f2o0j1k2l3m4"
down_revision = "e1n9i0j1k2l3"
branch_labels = None
depends_on = None

NEW_FK = "fk_notifications_post_id_forum_posts"


def _post_fks(inspector):
    return [
        fk for fk in inspector.get_foreign_keys("notifications")
        if fk.get("referred_table") == "forum_posts"
        and fk.get("constrained_columns") == ["post_id"]
    ]


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = _post_fks(inspector)
    with op.batch_alter_table("notifications") as batch:
        for fk in existing:
            name = fk.get("name")
            if name:
                batch.drop_constraint(name, type_="foreignkey")
        batch.create_foreign_key(
            NEW_FK,
            "forum_posts",
            ["post_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = _post_fks(inspector)
    with op.batch_alter_table("notifications") as batch:
        for fk in existing:
            name = fk.get("name")
            if name:
                batch.drop_constraint(name, type_="foreignkey")
        batch.create_foreign_key(
            "notifications_post_id_fkey",
            "forum_posts",
            ["post_id"],
            ["id"],
        )
