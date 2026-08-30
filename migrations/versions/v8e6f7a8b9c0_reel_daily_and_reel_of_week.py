"""reel reviews go daily; reel of the week becomes a member queue

Revision ID: v8e6f7a8b9c0
Revises: u7d5e6f7a8b9
"""
import sqlalchemy as sa
from alembic import op

revision = "v8e6f7a8b9c0"
down_revision = "u7d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("reel_reviews") as batch:
        batch.add_column(sa.Column("review_date", sa.Date(), nullable=True))
        batch.create_index("ix_reel_reviews_review_date", ["review_date"])
    # Reviews published before the daily schedule have no date of their own;
    # the day they were created is the honest answer.
    op.execute("UPDATE reel_reviews SET review_date = DATE(created_at) "
               "WHERE review_date IS NULL")

    op.create_table(
        "reel_submissions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("week_key", sa.Date(), nullable=False),
        sa.Column("reel_url", sa.String(length=500), nullable=False),
        sa.Column("share_count", sa.Integer(), nullable=False,
                  server_default="0"),
        sa.Column("disk_name", sa.String(length=64), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("mime", sa.String(length=120), nullable=False,
                  server_default="video/mp4"),
        sa.Column("size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("featured", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "week_key", name="uq_reel_sub_user_week"),
    )
    with op.batch_alter_table("reel_submissions") as batch:
        batch.create_index("ix_reel_submissions_user_id", ["user_id"])
        batch.create_index("ix_reel_submissions_week_key", ["week_key"])


def downgrade():
    with op.batch_alter_table("reel_submissions") as batch:
        batch.drop_index("ix_reel_submissions_week_key")
        batch.drop_index("ix_reel_submissions_user_id")
    op.drop_table("reel_submissions")
    with op.batch_alter_table("reel_reviews") as batch:
        batch.drop_index("ix_reel_reviews_review_date")
        batch.drop_column("review_date")
