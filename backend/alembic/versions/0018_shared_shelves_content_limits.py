"""Household: shared shelves and per-user content limits.

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-09 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0018'
down_revision: Union[str, Sequence[str], None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('max_content_rating', sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column('blocked_tags', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('hide_unrated', sa.Boolean(), server_default=sa.true(), nullable=False))
    with op.batch_alter_table('shelves', schema=None) as batch_op:
        batch_op.add_column(sa.Column('share_notes', sa.Boolean(), server_default=sa.false(), nullable=False))
    with op.batch_alter_table('shelf_novels', schema=None) as batch_op:
        batch_op.add_column(sa.Column('added_by_user_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key('fk_shelf_novels_added_by_user_id_users', 'users', ['added_by_user_id'], ['id'], ondelete='SET NULL')
    op.create_table('shelf_shares',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('shelf_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('permission', sa.String(length=16), server_default='view', nullable=False),
        sa.ForeignKeyConstraint(['shelf_id'], ['shelves.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shelf_id', 'user_id', name='uq_shelf_share_user'),
    )
    op.create_index(op.f('ix_shelf_shares_id'), 'shelf_shares', ['id'], unique=False)
    op.create_index(op.f('ix_shelf_shares_shelf_id'), 'shelf_shares', ['shelf_id'], unique=False)
    op.create_index(op.f('ix_shelf_shares_user_id'), 'shelf_shares', ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_shelf_shares_user_id'), table_name='shelf_shares')
    op.drop_index(op.f('ix_shelf_shares_shelf_id'), table_name='shelf_shares')
    op.drop_index(op.f('ix_shelf_shares_id'), table_name='shelf_shares')
    op.drop_table('shelf_shares')
    with op.batch_alter_table('shelf_novels', schema=None) as batch_op:
        batch_op.drop_constraint('fk_shelf_novels_added_by_user_id_users', type_='foreignkey')
        batch_op.drop_column('added_by_user_id')
    with op.batch_alter_table('shelves', schema=None) as batch_op:
        batch_op.drop_column('share_notes')
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_column('hide_unrated')
        batch_op.drop_column('blocked_tags')
        batch_op.drop_column('max_content_rating')
