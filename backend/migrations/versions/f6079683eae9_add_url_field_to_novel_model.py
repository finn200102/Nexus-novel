"""Add url field to Novel model

Revision ID: f6079683eae9
Revises: base
Create Date: 2025-03-14 19:12:13.118150

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6079683eae9'
down_revision: Union[str, None] = 'base'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add the url column to the novels table
    op.add_column('novels', sa.Column('url', sa.String(length=255), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Remove the url column from the novels table
    op.drop_column('novels', 'url')

