"""add_library_id_to_novels

Revision ID: 00d672a1cb4e
Revises: f6079683eae9
Create Date: 2025-03-15 23:15:09.046270

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '00d672a1cb4e'
down_revision: Union[str, None] = 'f6079683eae9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add library_id column to novels table
    op.add_column('novels', sa.Column('library_id', sa.Integer(), nullable=True))

    # Add foreign key constraint
    op.create_foreign_key(
        'fk_novels_library_id', 'novels', 'libraries',
        ['library_id'], ['id']
    )

    # If you want to make it not nullable right away (only if the table is empty)
    # Otherwise, you'll need to first populate the column with valid data
    # op.alter_column('novels', 'library_id', nullable=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop foreign key constraint
    op.drop_constraint('fk_novels_library_id', 'novels', type_='foreignkey')

    # Drop library_id column
    op.drop_column('novels', 'library_id')


