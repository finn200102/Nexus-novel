"""follow authors and series; new-work update events without a library novel

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-09 12:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0015'
down_revision: Union[str, Sequence[str], None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('creator_follows',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('site', sa.String(length=64), nullable=False),
    sa.Column('target_key', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=True),
    sa.Column('metadata_author_id', sa.Integer(), nullable=True),
    sa.Column('metadata_target_id', sa.Integer(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'kind', 'site', 'target_key', name='uq_creator_follow')
    )
    with op.batch_alter_table('creator_follows', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_creator_follows_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_creator_follows_metadata_target_id'), ['metadata_target_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_creator_follows_user_id'), ['user_id'], unique=False)

    with op.batch_alter_table('novel_update_events', schema=None) as batch_op:
        batch_op.alter_column('novel_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM novel_update_events WHERE novel_id IS NULL")
    with op.batch_alter_table('novel_update_events', schema=None) as batch_op:
        batch_op.alter_column('novel_id', existing_type=sa.Integer(), nullable=False)

    with op.batch_alter_table('creator_follows', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_creator_follows_user_id'))
        batch_op.drop_index(batch_op.f('ix_creator_follows_metadata_target_id'))
        batch_op.drop_index(batch_op.f('ix_creator_follows_id'))

    op.drop_table('creator_follows')
