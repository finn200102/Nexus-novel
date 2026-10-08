"""Library organization: blocklist, shelves, personal notes, rating and user tags.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0006'
down_revision: Union[str, Sequence[str], None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('blocklist_entries',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('value', sa.String(length=200), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'kind', 'value', name='uq_blocklist_user_kind_value')
    )
    with op.batch_alter_table('blocklist_entries', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_blocklist_entries_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_blocklist_entries_user_id'), ['user_id'], unique=False)

    op.create_table('shelves',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('position', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'name', name='uq_shelves_user_name')
    )
    with op.batch_alter_table('shelves', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_shelves_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_shelves_user_id'), ['user_id'], unique=False)

    op.create_table('shelf_novels',
    sa.Column('shelf_id', sa.Integer(), nullable=False),
    sa.Column('novel_id', sa.Integer(), nullable=False),
    sa.Column('position', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['shelf_id'], ['shelves.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('shelf_id', 'novel_id', name='uq_shelf_novel')
    )
    with op.batch_alter_table('shelf_novels', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_shelf_novels_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_shelf_novels_novel_id'), ['novel_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_shelf_novels_shelf_id'), ['shelf_id'], unique=False)

    op.create_table('novel_personal_data',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('novel_id', sa.Integer(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('rating', sa.Integer(), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'novel_id', name='uq_novel_personal_user_novel')
    )
    with op.batch_alter_table('novel_personal_data', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_novel_personal_data_id'), ['id'], unique=False)

    op.create_table('novel_user_tags',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('novel_id', sa.Integer(), nullable=False),
    sa.Column('tag', sa.String(length=60), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'novel_id', 'tag', name='uq_novel_user_tag')
    )
    with op.batch_alter_table('novel_user_tags', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_novel_user_tags_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_novel_user_tags_novel_id'), ['novel_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_novel_user_tags_user_id'), ['user_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('novel_user_tags')
    op.drop_table('novel_personal_data')
    op.drop_table('shelf_novels')
    op.drop_table('shelves')
    op.drop_table('blocklist_entries')
