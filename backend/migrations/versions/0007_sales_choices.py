"""sales pick lists: type of work, rough size, lost reason

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-15 09:00:00
"""
from alembic import op
import sqlalchemy as sa


revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.add_column(sa.Column('work_type', sa.String(length=100), server_default='', nullable=False))
        batch_op.add_column(sa.Column('value_band', sa.String(length=40), server_default='', nullable=False))
        batch_op.add_column(sa.Column('outcome_reason', sa.String(length=100), server_default='', nullable=False))


def downgrade():
    with op.batch_alter_table('jobs', schema=None) as batch_op:
        batch_op.drop_column('outcome_reason')
        batch_op.drop_column('value_band')
        batch_op.drop_column('work_type')
