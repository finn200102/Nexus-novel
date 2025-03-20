"""num_chapters Collumn

Revision ID: d6ec55f33cce
Revises: 889f5a442a63
Create Date: 2025-03-20 13:05:57.564823

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd6ec55f33cce'
down_revision: Union[str, None] = '889f5a442a63'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('novels', sa.Column('num_chapters', sa.Integer, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('novels', 'num_chapters')

