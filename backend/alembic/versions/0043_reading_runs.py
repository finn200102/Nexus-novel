"""Durable reading runs and journal; preserve legacy facts without inventing dates."""
from uuid import uuid4
from alembic import op
import sqlalchemy as sa

revision='0043'
down_revision='0042'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('reading_runs',
        sa.Column('id',sa.Integer(),primary_key=True),sa.Column('created_at',sa.DateTime()),sa.Column('updated_at',sa.DateTime()),
        sa.Column('run_key',sa.String(36),nullable=False,unique=True),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('novel_id',sa.Integer(),sa.ForeignKey('novels.id',ondelete='CASCADE'),nullable=False),
        sa.Column('ordinal',sa.Integer(),nullable=False),sa.Column('status',sa.String(20),nullable=False,server_default='active'),
        sa.Column('requires_run_key',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column('started_at',sa.DateTime()),sa.Column('started_at_inferred',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column('completed_at',sa.DateTime()),sa.Column('completed_at_inferred',sa.Boolean(),nullable=False,server_default=sa.false()),
        sa.Column('abandoned_at',sa.DateTime()),sa.Column('abandon_reason',sa.String(500)),sa.Column('archived_at',sa.DateTime()),
        sa.Column('progress_snapshot',sa.JSON(),nullable=False,server_default='{}'),
        sa.UniqueConstraint('user_id','novel_id','ordinal',name='uq_reading_run_ordinal'))
    op.create_table('reading_run_events',
        sa.Column('id',sa.Integer(),primary_key=True),sa.Column('created_at',sa.DateTime()),sa.Column('updated_at',sa.DateTime()),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('novel_id',sa.Integer(),sa.ForeignKey('novels.id',ondelete='CASCADE'),nullable=False),
        sa.Column('run_key',sa.String(36),sa.ForeignKey('reading_runs.run_key',ondelete='CASCADE'),nullable=False),
        sa.Column('kind',sa.String(20),nullable=False),sa.Column('occurred_at',sa.DateTime()),
        sa.Column('inferred',sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column('reason',sa.String(500)))
    for table,columns in [('reading_runs',('id','user_id','novel_id')),('reading_run_events',('id','user_id','novel_id','run_key'))]:
        for column in columns:op.create_index(f'ix_{table}_{column}',table,[column])
    op.add_column('reading_progress',sa.Column('reading_run_key',sa.String(36)))
    op.add_column('reading_history',sa.Column('reading_run_key',sa.String(36)))
    bind=op.get_bind()
    metadata=sa.MetaData()
    progress=sa.Table('reading_progress',metadata,autoload_with=bind)
    history=sa.Table('reading_history',metadata,autoload_with=bind)
    chapters=sa.Table('chapters',metadata,autoload_with=bind)
    runs=sa.Table('reading_runs',metadata,autoload_with=bind)
    events=sa.Table('reading_run_events',metadata,autoload_with=bind)
    pairs=sa.union(sa.select(progress.c.user_id,progress.c.novel_id),sa.select(history.c.user_id,history.c.novel_id)).subquery()
    last_user,last_novel=-1,-1
    while True:
        rows=bind.execute(sa.select(pairs).where(sa.or_(pairs.c.user_id>last_user,
            sa.and_(pairs.c.user_id==last_user,pairs.c.novel_id>last_novel))).order_by(pairs.c.user_id,pairs.c.novel_id).limit(250)).all()
        if not rows:break
        for user_id,novel_id in rows:
            key=str(uuid4())
            row=bind.execute(sa.select(progress).where(progress.c.user_id==user_id,progress.c.novel_id==novel_id)).mappings().first()
            snapshot={name:row[name] for name in ('novel_id','chapter_number','position','percent','revision','furthest_chapter_number','furthest_percent','block_id','text_offset','text_quote','quote_prefix','quote_suffix','locator_content_version','locator_variant')} if row else {}
            if row:snapshot['updated_at']=row['updated_at'].isoformat() if row['updated_at'] else None
            snapshot['reading_run_key']=key
            last=bind.execute(sa.select(sa.func.max(chapters.c.chapter_number)).where(chapters.c.novel_id==novel_id)).scalar()
            history_completed=bind.execute(sa.select(history.c.id).where(history.c.user_id==user_id,history.c.novel_id==novel_id,history.c.chapter_number==last,history.c.max_percent>=95).limit(1)).first() if last is not None else None
            completed=bool(history_completed or (row and last is not None and row['chapter_number']==last and (row['percent'] or 0)>=95))
            bind.execute(runs.insert().values(run_key=key,user_id=user_id,novel_id=novel_id,ordinal=1,
                status='completed' if completed else 'active',started_at_inferred=True,completed_at_inferred=completed,progress_snapshot=snapshot))
            for kind in (['started','completed'] if completed else ['started']):
                bind.execute(events.insert().values(user_id=user_id,novel_id=novel_id,run_key=key,kind=kind,inferred=True))
            bind.execute(progress.update().where(progress.c.user_id==user_id,progress.c.novel_id==novel_id).values(reading_run_key=key))
            bind.execute(history.update().where(history.c.user_id==user_id,history.c.novel_id==novel_id).values(reading_run_key=key))
        last_user,last_novel=rows[-1]
    with op.batch_alter_table('reading_history') as batch:
        batch.drop_constraint('uq_reading_history_day',type_='unique')
        batch.create_unique_constraint('uq_reading_history_day_run',['user_id','novel_id','chapter_number','reading_date','reading_run_key'])


def downgrade():
    bind=op.get_bind()
    table=sa.Table('reading_history',sa.MetaData(),autoload_with=bind)
    # Legacy history has only one point per chapter/day: compact reread points
    # conservatively, keeping the maximum completion before removing run keys.
    groups=bind.execute(sa.select(table.c.user_id,table.c.novel_id,table.c.chapter_number,sa.func.date(table.c.reading_date),
        sa.func.min(table.c.id),sa.func.max(table.c.max_percent)).group_by(table.c.user_id,table.c.novel_id,table.c.chapter_number,sa.func.date(table.c.reading_date)).having(sa.func.count()>1)).all()
    for user,novel,chapter,day,keep,percent in groups:
        bind.execute(table.update().where(table.c.id==keep).values(max_percent=percent))
        bind.execute(table.delete().where(table.c.user_id==user,table.c.novel_id==novel,table.c.chapter_number==chapter,sa.func.date(table.c.reading_date)==day,table.c.id!=keep))
    with op.batch_alter_table('reading_history') as batch:
        batch.drop_constraint('uq_reading_history_day_run',type_='unique')
        batch.drop_column('reading_run_key')
        batch.create_unique_constraint('uq_reading_history_day',['user_id','novel_id','chapter_number','reading_date'])
    with op.batch_alter_table('reading_progress') as batch:batch.drop_column('reading_run_key')
    op.drop_table('reading_run_events');op.drop_table('reading_runs')
