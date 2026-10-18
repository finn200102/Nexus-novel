"""Canonical completion facts survive continuation between owned story copies."""
from uuid import NAMESPACE_URL, uuid5
from datetime import datetime
from alembic import op
import sqlalchemy as sa

revision = '0045'
down_revision = '0044'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('reading_continuities',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('created_at', sa.DateTime()), sa.Column('updated_at', sa.DateTime()),
        sa.Column('continuity_key', sa.String(36), nullable=False, unique=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('work_key', sa.String(36), nullable=False), sa.Column('logical_ordinal', sa.Integer(), nullable=False),
        sa.Column('completed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('completed_at', sa.DateTime()), sa.Column('completed_at_inferred', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('completion_novel_id', sa.Integer(), sa.ForeignKey('novels.id', ondelete='SET NULL')))
    for column in ('id', 'user_id', 'work_key'):
        op.create_index(f'ix_reading_continuities_{column}', 'reading_continuities', [column])
    with op.batch_alter_table('reading_runs') as batch:
        batch.add_column(sa.Column('continuity_key', sa.String(36), nullable=True))
        batch.create_foreign_key('fk_reading_runs_continuity', 'reading_continuities', ['continuity_key'], ['continuity_key'])
        batch.create_index('ix_reading_runs_continuity_key', ['continuity_key'])
    bind = op.get_bind(); metadata = sa.MetaData()
    runs = sa.Table('reading_runs', metadata, autoload_with=bind)
    events = sa.Table('reading_run_events', metadata, autoload_with=bind)
    users = sa.Table('users', metadata, autoload_with=bind)
    groups = sa.Table('reading_continuities', metadata, autoload_with=bind)
    last_id = 0
    while True:
        rows = bind.execute(sa.select(runs, users.c.storage_id).join(users, users.c.id == runs.c.user_id).where(runs.c.id > last_id).order_by(runs.c.id).limit(250)).mappings().all()
        if not rows:break
        for row in rows:
            completed = bind.execute(sa.select(events.c.occurred_at, events.c.inferred).where(
                events.c.user_id == row['user_id'], events.c.novel_id == row['novel_id'], events.c.run_key == row['run_key'], events.c.kind == 'completed')).all()
            # Exactly the prior stats preference: known exact facts first,
            # otherwise retain the undated/inferred state without guessing.
            completed.sort(key=lambda fact:(bool(fact.inferred or fact.occurred_at is None), fact.occurred_at or datetime.max))
            fact = completed[0] if completed else None
            portable = (row['progress_snapshot'] or {}).get('_portable_ordinal')
            ordinal = portable if type(portable) is int and portable > 0 else row['ordinal']
            bind.execute(groups.insert().values(continuity_key=row['run_key'], user_id=row['user_id'],
                work_key=str(uuid5(NAMESPACE_URL, f"nexus-reading-work:{row['storage_id']}:{row['novel_id']}")), logical_ordinal=ordinal,
                completed=fact is not None, completed_at=fact.occurred_at if fact else None,
                completed_at_inferred=bool(fact.inferred or fact.occurred_at is None) if fact else False,
                completion_novel_id=row['novel_id'] if fact else None, created_at=row['created_at'], updated_at=row['updated_at']))
            bind.execute(runs.update().where(runs.c.id == row['id']).values(continuity_key=row['run_key']))
        last_id = rows[-1]['id']


def downgrade():
    with op.batch_alter_table('reading_runs') as batch:
        batch.drop_index('ix_reading_runs_continuity_key')
        batch.drop_constraint('fk_reading_runs_continuity', type_='foreignkey')
        batch.drop_column('continuity_key')
    op.drop_table('reading_continuities')
