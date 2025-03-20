"""chapter title to nullable

Revision ID: c3b249ed9002
Revises: d6ec55f33cce
Create Date: 2025-03-20 13:11:20.038957

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3b249ed9002'
down_revision: Union[str, None] = 'd6ec55f33cce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Drop the index first
    op.drop_index('ix_chapters_title', table_name='chapters')

    # Then alter the column to be nullable
    op.alter_column('chapters', 'title',
                    existing_type=sa.String(255),
                    nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # First make the column non-nullable again
    op.alter_column('chapters', 'title',
                    existing_type=sa.String(255),
                    nullable=False)

    # Then recreate the index
    op.create_index('ix_chapters_title', 'chapters', ['title'])

