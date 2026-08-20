"""Add features_json to membership_plans for Studio feature toggles."""
from alembic import op
import sqlalchemy as sa


revision = "a7j5e6f7g8h9"
down_revision = "z6i4d5e6f7g8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("membership_plans") as batch:
        batch.add_column(sa.Column("features_json", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("membership_plans") as batch:
        batch.drop_column("features_json")
