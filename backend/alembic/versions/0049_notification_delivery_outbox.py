"""Durable per-destination notification attempts (legacy events stay closed)."""
from alembic import op
import sqlalchemy as sa
from uuid import uuid4

revision='0049'
down_revision='0048'
branch_labels=None
depends_on=None


def upgrade():
    bind=op.get_bind()
    for name in ('push_subscriptions','notification_channels'):
        op.add_column(name,sa.Column('delivery_key',sa.String(36),nullable=True))
        op.add_column(name,sa.Column('eligibility_event_id',sa.Integer(),nullable=True))
        table=sa.table(name,sa.column('id',sa.Integer()),sa.column('delivery_key',sa.String(36)),sa.column('eligibility_event_id',sa.Integer()))
        last=0
        while True:
            ids=bind.execute(sa.select(table.c.id).where(table.c.id>last).order_by(table.c.id).limit(250)).scalars().all()
            if not ids:break
            for identity in ids:bind.execute(table.update().where(table.c.id==identity).values(delivery_key=str(uuid4()),eligibility_event_id=0))
            last=ids[-1]
    op.create_table('notification_deliveries',
        sa.Column('id',sa.Integer(),primary_key=True),sa.Column('created_at',sa.DateTime()),sa.Column('updated_at',sa.DateTime()),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('account_key',sa.String(36),nullable=False),sa.Column('delivery_key',sa.String(36),nullable=False,unique=True),
        sa.Column('destination_kind',sa.String(16),nullable=False),sa.Column('destination_id',sa.Integer(),nullable=False),
        sa.Column('destination_fingerprint',sa.String(64),nullable=False),sa.Column('payload',sa.JSON(),nullable=False),sa.Column('event_ids',sa.JSON(),nullable=False),
        sa.Column('status',sa.String(24),nullable=False,server_default='queued'),sa.Column('attempt_count',sa.Integer(),nullable=False,server_default='0'),
        sa.Column('next_attempt_at',sa.DateTime()),sa.Column('lease_owner',sa.String(36)),sa.Column('lease_expires_at',sa.DateTime()),
        sa.Column('finished_at',sa.DateTime()),sa.Column('last_error_code',sa.String(64)))
    op.create_index('ix_notification_deliveries_id','notification_deliveries',['id'])
    op.create_index('ix_notification_deliveries_user_id','notification_deliveries',['user_id'])
    op.create_index('ix_notification_deliveries_due','notification_deliveries',['status','next_attempt_at','lease_expires_at'])


def downgrade():
    op.drop_table('notification_deliveries')
    for name in ('notification_channels','push_subscriptions'):
        op.drop_column(name,'eligibility_event_id')
        op.drop_column(name,'delivery_key')
