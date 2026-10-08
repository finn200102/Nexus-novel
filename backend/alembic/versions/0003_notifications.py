"""Notifications: Web Push subscriptions, Apprise channels, and a delivered
marker on update events.

Existing update events are marked as already notified, so the first worker
start after upgrading does not replay the account's history to new devices.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0003'
down_revision: Union[str, Sequence[str], None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('push_subscriptions',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('endpoint', sa.String(length=2048), nullable=False),
    sa.Column('p256dh', sa.String(length=255), nullable=False),
    sa.Column('auth', sa.String(length=64), nullable=False),
    sa.Column('user_agent', sa.String(length=255), nullable=True),
    sa.Column('last_success_at', sa.DateTime(), nullable=True),
    sa.Column('failure_count', sa.Integer(), server_default='0', nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('endpoint', name='uq_push_subscription_endpoint')
    )
    op.create_index(op.f('ix_push_subscriptions_id'), 'push_subscriptions', ['id'], unique=False)
    op.create_index(op.f('ix_push_subscriptions_user_id'), 'push_subscriptions', ['user_id'], unique=False)
    op.create_table('notification_channels',
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=20), server_default='apprise', nullable=False),
    sa.Column('url_encrypted', sa.Text(), nullable=False),
    sa.Column('url_hint', sa.String(length=255), server_default='', nullable=False),
    sa.Column('label', sa.String(length=120), server_default='', nullable=False),
    sa.Column('enabled', sa.Boolean(), server_default='1', nullable=False),
    sa.Column('last_error', sa.String(length=255), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notification_channels_id'), 'notification_channels', ['id'], unique=False)
    op.create_index(op.f('ix_notification_channels_user_id'), 'notification_channels', ['user_id'], unique=False)
    op.add_column('novel_update_events', sa.Column('notified_at', sa.DateTime(), nullable=True))
    op.execute(sa.text("UPDATE novel_update_events SET notified_at = CURRENT_TIMESTAMP"))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('novel_update_events', 'notified_at')
    op.drop_index(op.f('ix_notification_channels_user_id'), table_name='notification_channels')
    op.drop_index(op.f('ix_notification_channels_id'), table_name='notification_channels')
    op.drop_table('notification_channels')
    op.drop_index(op.f('ix_push_subscriptions_user_id'), table_name='push_subscriptions')
    op.drop_index(op.f('ix_push_subscriptions_id'), table_name='push_subscriptions')
    op.drop_table('push_subscriptions')
