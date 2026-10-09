"""Native Kobo sync: devices with path tokens and what each device holds.

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-09 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0019'
down_revision: Union[str, Sequence[str], None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('kobo_devices',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=120), nullable=False),
        sa.Column('token_hash', sa.String(length=64), nullable=False),
        sa.Column('shelf_id', sa.Integer(), nullable=True),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('last_sync_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['shelf_id'], ['shelves.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('token_hash'),
    )
    op.create_index(op.f('ix_kobo_devices_id'), 'kobo_devices', ['id'], unique=False)
    op.create_index(op.f('ix_kobo_devices_user_id'), 'kobo_devices', ['user_id'], unique=False)
    op.create_table('kobo_synced_books',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('device_id', sa.Integer(), nullable=False),
        sa.Column('novel_id', sa.Integer(), nullable=False),
        sa.Column('entitlement_id', sa.String(length=36), nullable=False),
        sa.Column('fingerprint', sa.String(length=64), server_default='', nullable=False),
        sa.Column('removed', sa.Boolean(), server_default='0', nullable=False),
        sa.Column('state_sent_at', sa.DateTime(), nullable=True),
        sa.Column('bookmark_source', sa.String(length=255), nullable=True),
        sa.Column('bookmark_value', sa.String(length=255), nullable=True),
        sa.Column('bookmark_type', sa.String(length=40), nullable=True),
        sa.Column('progress_percent', sa.Float(), nullable=True),
        sa.Column('content_percent', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('bookmark_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['device_id'], ['kobo_devices.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('device_id', 'novel_id', name='uq_kobo_synced_book_device_novel'),
    )
    op.create_index('ix_kobo_synced_books_device_entitlement', 'kobo_synced_books', ['device_id', 'entitlement_id'], unique=False)
    op.create_index(op.f('ix_kobo_synced_books_id'), 'kobo_synced_books', ['id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_kobo_synced_books_id'), table_name='kobo_synced_books')
    op.drop_index('ix_kobo_synced_books_device_entitlement', table_name='kobo_synced_books')
    op.drop_table('kobo_synced_books')
    op.drop_index(op.f('ix_kobo_devices_user_id'), table_name='kobo_devices')
    op.drop_index(op.f('ix_kobo_devices_id'), table_name='kobo_devices')
    op.drop_table('kobo_devices')
