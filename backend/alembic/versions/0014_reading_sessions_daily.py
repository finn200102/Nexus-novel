"""reading sessions daily

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-09 09:14:26.233637

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0014'
down_revision: Union[str, Sequence[str], None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('reading_sessions_daily',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('novel_id', sa.Integer(), nullable=False),
    sa.Column('seconds', sa.Integer(), server_default='0', nullable=False),
    sa.Column('words', sa.Integer(), server_default='0', nullable=False),
    sa.Column('chapters_finished', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'day', 'novel_id', name='uq_reading_sessions_daily')
    )
    with op.batch_alter_table('reading_sessions_daily', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_reading_sessions_daily_day'), ['day'], unique=False)
        batch_op.create_index(batch_op.f('ix_reading_sessions_daily_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_reading_sessions_daily_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('reading_sessions_daily', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_reading_sessions_daily_user_id'))
        batch_op.drop_index(batch_op.f('ix_reading_sessions_daily_id'))
        batch_op.drop_index(batch_op.f('ix_reading_sessions_daily_day'))

    op.drop_table('reading_sessions_daily')
