"""add_custom_service_fields_to_slots

Revision ID: c1d2e3f4a5b6
Revises: baceca7a212f
Create Date: 2026-09-03 19:10:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'baceca7a212f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Allow service_id to be nullable for pure custom/ad-hoc slots
    op.alter_column('slots', 'service_id', existing_type=sa.Integer(), nullable=True)
    # Add custom display/override fields
    op.add_column('slots', sa.Column('custom_service_name', sa.String(length=100), nullable=True))
    op.add_column('slots', sa.Column('custom_price', sa.Numeric(precision=10, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column('slots', 'custom_price')
    op.drop_column('slots', 'custom_service_name')
    op.alter_column('slots', 'service_id', existing_type=sa.Integer(), nullable=False)
