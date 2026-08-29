"""contact messages: triage status for the Studio inbox

Revision ID: u7d5e6f7a8b9
Revises: t6c4d5e6f7a8
"""
import sqlalchemy as sa
from alembic import op

revision = "u7d5e6f7a8b9"
down_revision = "t6c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("contact_messages") as batch:
        batch.add_column(sa.Column("status", sa.String(length=20),
                                   nullable=False, server_default="new"))
        batch.create_index("ix_contact_messages_status", ["status"])
    # Messages that predate the Inbox were only ever seen by email, so leaving
    # them as "new" would drop a pile of stale work on the owners.
    op.execute("UPDATE contact_messages SET status = 'reviewed'")


def downgrade():
    with op.batch_alter_table("contact_messages") as batch:
        batch.drop_index("ix_contact_messages_status")
        batch.drop_column("status")
