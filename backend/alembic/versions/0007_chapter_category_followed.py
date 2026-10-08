"""Chapter category and per-novel followed categories.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-08 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('chapters', schema=None) as batch_op:
        batch_op.add_column(sa.Column('category', sa.String(length=32), server_default='story', nullable=False))

    with op.batch_alter_table('novel_personal_data', schema=None) as batch_op:
        batch_op.add_column(sa.Column('followed_categories', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('novel_personal_data', schema=None) as batch_op:
        batch_op.drop_column('followed_categories')

    with op.batch_alter_table('chapters', schema=None) as batch_op:
        batch_op.drop_column('category')
