"""chapter number

Revision ID: 8b0628939ca4
Revises: c3b249ed9002
Create Date: 2025-03-20 13:16:19.324528

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8b0628939ca4'
down_revision: Union[str, None] = 'c3b249ed9002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('chapters', sa.Column('chapter_number', sa.Integer, nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chapters', 'chapter_number')

