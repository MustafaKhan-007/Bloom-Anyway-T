"""Allow multiple journal pages per day.

Revision ID: k7t5u6v7w8x9
Revises: j6s4n5o6p7q8
"""
from alembic import op


revision = "k7t5u6v7w8x9"
down_revision = "j6s4n5o6p7q8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("journal_entries") as batch:
        batch.drop_constraint("uq_journal_user_day", type_="unique")
        batch.create_index(
            "ix_journal_entries_user_day",
            ["user_id", "day"],
        )


def downgrade():
    with op.batch_alter_table("journal_entries") as batch:
        batch.drop_index("ix_journal_entries_user_day")
        batch.create_unique_constraint(
            "uq_journal_user_day", ["user_id", "day"],
        )
