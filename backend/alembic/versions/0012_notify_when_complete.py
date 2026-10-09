"""Per-user opt-in to a "completed" update event.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('novel_personal_data', schema=None) as batch_op:
        batch_op.add_column(sa.Column('notify_when_complete', sa.Boolean(), server_default=sa.false(), nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('novel_personal_data', schema=None) as batch_op:
        batch_op.drop_column('notify_when_complete')
