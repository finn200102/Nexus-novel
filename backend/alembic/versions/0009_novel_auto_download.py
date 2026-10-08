"""Per-novel auto-download settings.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-08 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0009'
down_revision: Union[str, Sequence[str], None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('novel_personal_data', schema=None) as batch_op:
        batch_op.add_column(sa.Column('auto_download', sa.Boolean(), server_default=sa.false(), nullable=False))
        batch_op.add_column(sa.Column('keep_ahead', sa.Integer(), server_default='10', nullable=False))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('novel_personal_data', schema=None) as batch_op:
        batch_op.drop_column('keep_ahead')
        batch_op.drop_column('auto_download')
