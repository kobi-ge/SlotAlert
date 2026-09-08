"""add_whatsapp_fields_to_broadcast_logs

Revision ID: d3e4f5a6b7c8
Revises: c1d2e3f4a5b6
Create Date: 2026-09-08 17:50:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('broadcast_logs', sa.Column('wamid', sa.String(length=128), nullable=True))
    op.create_index(op.f('ix_broadcast_logs_wamid'), 'broadcast_logs', ['wamid'], unique=False)
    op.add_column('broadcast_logs', sa.Column('meta_error_code', sa.Integer(), nullable=True))
    op.add_column('broadcast_logs', sa.Column('failure_reason', sa.String(length=255), nullable=True))
    op.add_column('broadcast_logs', sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('broadcast_logs', sa.Column('read_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('broadcast_logs', 'read_at')
    op.drop_column('broadcast_logs', 'delivered_at')
    op.drop_column('broadcast_logs', 'failure_reason')
    op.drop_column('broadcast_logs', 'meta_error_code')
    op.drop_index(op.f('ix_broadcast_logs_wamid'), table_name='broadcast_logs')
    op.drop_column('broadcast_logs', 'wamid')
