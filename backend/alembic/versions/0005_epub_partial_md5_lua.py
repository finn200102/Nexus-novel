"""Store KOReader's LuaJIT partial MD5 for each EPUB build.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('epub_builds', schema=None) as batch_op:
        batch_op.add_column(sa.Column('partial_md5_lua', sa.String(length=32), nullable=True))
        batch_op.create_index(batch_op.f('ix_epub_builds_partial_md5_lua'), ['partial_md5_lua'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('epub_builds', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_epub_builds_partial_md5_lua'))
        batch_op.drop_column('partial_md5_lua')
