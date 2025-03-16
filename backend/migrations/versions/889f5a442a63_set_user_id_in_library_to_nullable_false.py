"""Set user_id in library to nullable False

Revision ID: 889f5a442a63
Revises: 00d672a1cb4e
Create Date: 2025-03-16 16:23:03.426346

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '889f5a442a63'
down_revision: Union[str, None] = '00d672a1cb4e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column('libraries', 'user_id',
               existing_type=sa.INTEGER(),
               nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column('libraries', 'user_id',
               existing_type=sa.INTEGER(),
               nullable=True)

