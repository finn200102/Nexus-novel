"""Highlight export: Readwise connections and per-annotation export marker.

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-09 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0017'
down_revision: Union[str, Sequence[str], None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('reading_annotations', schema=None) as batch_op:
        batch_op.add_column(sa.Column('exported_at', sa.DateTime(), nullable=True))
    op.create_table('readwise_connections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('token_encrypted', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_readwise_connection_user'),
    )
    op.create_index(op.f('ix_readwise_connections_id'), 'readwise_connections', ['id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_readwise_connections_id'), table_name='readwise_connections')
    op.drop_table('readwise_connections')
    with op.batch_alter_table('reading_annotations', schema=None) as batch_op:
        batch_op.drop_column('exported_at')
