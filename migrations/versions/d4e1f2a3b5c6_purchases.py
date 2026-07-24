"""purchases table for Lemon Squeezy shop downloads

Revision ID: d4e1f2a3b5c6
Revises: c3d0e1f2a4b5
Create Date: 2026-07-24 17:20:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd4e1f2a3b5c6'
down_revision = 'c3d0e1f2a4b5'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'purchases',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('product_id', sa.String(length=40), nullable=True),
        sa.Column('variant_id', sa.String(length=40), nullable=True),
        sa.Column('product_name', sa.String(length=200), nullable=False, server_default=''),
        sa.Column('order_id', sa.String(length=40), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='paid'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('order_id'),
    )
    with op.batch_alter_table('purchases', schema=None) as batch_op:
        batch_op.create_index('ix_purchases_email', ['email'])
        batch_op.create_index('ix_purchases_user_id', ['user_id'])
        batch_op.create_index('ix_purchases_variant_id', ['variant_id'])


def downgrade():
    with op.batch_alter_table('purchases', schema=None) as batch_op:
        batch_op.drop_index('ix_purchases_variant_id')
        batch_op.drop_index('ix_purchases_user_id')
        batch_op.drop_index('ix_purchases_email')
    op.drop_table('purchases')
