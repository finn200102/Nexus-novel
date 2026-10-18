"""0045 adds identity without changing existing completion measurements."""
import os
from datetime import datetime
from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import create_engine, text, Table, MetaData, inspect
from app.db_migrations import alembic_config


@pytest.mark.parametrize('dialect',['sqlite','postgresql'])
def test_0045_backfills_existing_event_counts_dates_and_portable_meaning(tmp_path,dialect):
    admin=None
    if dialect=='postgresql':
        url=os.environ.get('NEXUS_TEST_POSTGRES_URL')
        if not url:pytest.skip('An owned disposable PostgreSQL URL is required')
        admin=create_engine(url);schema='continuity_migration_'+uuid4().hex
        with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
    else:engine=create_engine(f'sqlite:///{tmp_path / "continuity.db"}')
    try:
        with engine.connect() as connection:
            command.upgrade(alembic_config(connection),'0044');connection.commit()
            connection.execute(text("INSERT INTO users (id,username,password,storage_id) VALUES (1,'owner','unused','continuity-owner')"))
            connection.execute(text("INSERT INTO libraries (id,user_id,name) VALUES (1,1,'Fixture')"))
            connection.execute(text("INSERT INTO novels (id,library_id,title) VALUES (1,1,'Fixture')"))
            runs=Table('reading_runs',MetaData(),autoload_with=connection)
            events=Table('reading_run_events',MetaData(),autoload_with=connection)
            keys=[str(uuid4()) for _ in range(4)]
            when=datetime(2024,2,29,12,30)
            for index,key in enumerate(keys,1):
                connection.execute(runs.insert().values(id=index,user_id=1,novel_id=1,run_key=key,ordinal=index,
                    status='active',progress_snapshot={'_portable_ordinal':1 if index==2 else True},started_at_inferred=True))
            connection.execute(events.insert(),[
                dict(user_id=1,novel_id=1,run_key=keys[0],kind='completed',occurred_at=when,inferred=False),
                dict(user_id=1,novel_id=1,run_key=keys[0],kind='completed',occurred_at=None,inferred=True),
                dict(user_id=1,novel_id=1,run_key=keys[1],kind='completed',occurred_at=None,inferred=True),
                dict(user_id=1,novel_id=1,run_key=keys[2],kind='completed',occurred_at=datetime(2099,1,1),inferred=False)])
            connection.commit();command.upgrade(alembic_config(connection),'0045');connection.commit()
            groups=Table('reading_continuities',MetaData(),autoload_with=connection)
            rows=connection.execute(groups.select().order_by(groups.c.id)).mappings().all()
            assert [row['continuity_key'] for row in rows]==keys
            assert [row['logical_ordinal'] for row in rows]==[1,1,3,4]  # bool metadata is not an ordinal.
            assert [row['completed'] for row in rows]==[True,True,True,False]
            assert [row['completed_at'] for row in rows]==[when,None,datetime(2099,1,1),None]
            assert [row['completed_at_inferred'] for row in rows]==[False,True,False,False]
            assert len({row['work_key'] for row in rows})==1
            assert connection.execute(text('SELECT COUNT(*) FROM reading_run_events')).scalar()==4
            assert connection.execute(text('SELECT COUNT(*) FROM reading_runs WHERE continuity_key IS NOT NULL')).scalar()==4
            command.downgrade(alembic_config(connection),'0044');connection.commit()
            assert 'reading_continuities' not in inspect(connection).get_table_names()
            assert connection.execute(text('SELECT COUNT(*) FROM reading_run_events')).scalar()==4
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            admin.dispose()
