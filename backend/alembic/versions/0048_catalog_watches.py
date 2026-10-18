"""Private catalog query activation, baseline receipts and durable matches."""
from uuid import uuid4
from alembic import op
import sqlalchemy as sa

revision = '0048'
down_revision = '0047'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('saved_searches', sa.Column('identity_key', sa.String(36), nullable=True))
    bind = op.get_bind()
    searches = sa.table('saved_searches', sa.column('id', sa.Integer()), sa.column('identity_key', sa.String(36)))
    last = 0
    while True:
        ids = bind.execute(sa.select(searches.c.id).where(searches.c.id > last).order_by(searches.c.id).limit(250)).scalars().all()
        if not ids: break
        for id in ids:
            bind.execute(searches.update().where(searches.c.id == id).values(identity_key=str(uuid4())))
        last = ids[-1]
    op.create_index('uq_saved_searches_identity_key', 'saved_searches', ['identity_key'], unique=True)
    op.create_table('catalog_watches',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime()), sa.Column('updated_at', sa.DateTime()),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('search_id', sa.Integer(), sa.ForeignKey('saved_searches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('search_key', sa.String(36), nullable=False), sa.Column('account_key', sa.String(36), nullable=False),
        sa.Column('identity_key', sa.String(36), nullable=False, unique=True),
        sa.Column('revision', sa.String(64), nullable=False), sa.Column('search_revision', sa.String(64), nullable=False),
        sa.Column('permission_fingerprint', sa.String(64), nullable=False),
        sa.Column('status', sa.String(24), nullable=False), sa.Column('mode', sa.String(16), nullable=False),
        sa.Column('prepared', sa.JSON(), nullable=False), sa.Column('prepared_revision', sa.String(64), nullable=False),
        sa.Column('epoch', sa.String(36), nullable=False), sa.Column('cursor', sa.BigInteger(), nullable=False),
        sa.Column('baseline', sa.JSON()), sa.Column('baseline_total', sa.Integer()),
        sa.Column('baseline_offset', sa.Integer(), nullable=False),
        sa.Column('last_checked_at', sa.DateTime()), sa.Column('reason', sa.String(64)),
        sa.Column('lease_owner', sa.String(36)), sa.Column('lease_expires_at', sa.DateTime()),
        sa.Column('next_check_at', sa.DateTime()),
        sa.UniqueConstraint('user_id', 'search_id', name='uq_catalog_watch_search'))
    op.create_table('catalog_watch_seen',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime()), sa.Column('updated_at', sa.DateTime()),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('watch_id', sa.Integer(), sa.ForeignKey('catalog_watches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('work_key', sa.String(36), nullable=False),
        sa.UniqueConstraint('watch_id', 'work_key', name='uq_catalog_watch_seen'))
    op.create_table('catalog_matches',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime()), sa.Column('updated_at', sa.DateTime()),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('watch_id', sa.Integer(), sa.ForeignKey('catalog_watches.id', ondelete='CASCADE'), nullable=False),
        sa.Column('work_key', sa.String(36), nullable=False), sa.Column('novel', sa.JSON(), nullable=False),
        sa.Column('event_id', sa.Integer(), sa.ForeignKey('novel_update_events.id', ondelete='SET NULL')),
        sa.Column('read_at', sa.DateTime()),
        sa.UniqueConstraint('watch_id', 'work_key', name='uq_catalog_match_work'))
    for table, columns in {'catalog_watches': ('id','user_id','search_id','status'), 'catalog_watch_seen': ('id','user_id','watch_id'), 'catalog_matches': ('id','user_id','watch_id')}.items():
        for column in columns: op.create_index(f'ix_{table}_{column}', table, [column])


def downgrade():
    for table in ('catalog_matches', 'catalog_watch_seen', 'catalog_watches'): op.drop_table(table)
    op.drop_index('uq_saved_searches_identity_key', table_name='saved_searches')
    op.drop_column('saved_searches', 'identity_key')
