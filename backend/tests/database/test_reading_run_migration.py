import os
from uuid import UUID,uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from alembic import command
from sqlalchemy import create_engine,inspect,text,Table,MetaData,select
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from app.db_migrations import alembic_config,upgrade_database
from app.models import User,Library,Novel,Chapter,ReadingProgress,ReadingRun,ReadingRunEvent
from app.services.reading_progress_service import save_reading_progress
from app.services.reading_run_service import action
from app.schemas.reading_runs import ReadingRunAction


@pytest.fixture(params=['sqlite','postgresql'])
def run_engine(request,tmp_path):
    admin=None;schema=None
    if request.param=='postgresql':
        url=os.environ.get('NEXUS_TEST_POSTGRES_URL')
        if not url:pytest.skip('Set NEXUS_TEST_POSTGRES_URL to an owned disposable PostgreSQL database')
        admin=create_engine(url);schema='reading_runs_'+uuid4().hex
        with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
    else:engine=create_engine(f'sqlite:///{tmp_path / "runs-migration.db"}')
    try:yield engine
    finally:
        engine.dispose()
        if admin:
            with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            admin.dispose()


def test_0043_preserves_legacy_completion_and_history_without_fabricating_dates(run_engine):
    with run_engine.connect() as connection:
        command.upgrade(alembic_config(connection),'0042');connection.commit()
        user=connection.execute(text("INSERT INTO users(username,password,storage_id) VALUES('legacy','unused',:key) RETURNING id"),{'key':str(uuid4())}).scalar_one()
        library=connection.execute(text("INSERT INTO libraries(name,user_id) VALUES('Private',:user) RETURNING id"),{'user':user}).scalar_one()
        novel=connection.execute(text("INSERT INTO novels(title,library_id) VALUES('Legacy story',:library) RETURNING id"),{'library':library}).scalar_one()
        chapter=connection.execute(text("INSERT INTO chapters(novel_id,chapter_number,title,content_status,audio_status,retry_count) VALUES(:novel,2,'Final','PRESENT','MISSING',0) RETURNING id"),{'novel':novel}).scalar_one()
        connection.execute(text("INSERT INTO reading_progress(user_id,novel_id,chapter_id,chapter_number,position,percent,revision,furthest_chapter_number,furthest_percent,updated_at) VALUES(:user,:novel,:chapter,2,300,100,7,2,100,'2026-01-02 00:00:00')"),dict(user=user,novel=novel,chapter=chapter))
        connection.execute(text("INSERT INTO reading_history(user_id,novel_id,chapter_number,reading_date,max_percent) VALUES(:user,:novel,2,'2026-01-02 00:00:00',100)"),dict(user=user,novel=novel));connection.commit()
        command.upgrade(alembic_config(connection),'0043');connection.commit()
    with sessionmaker(bind=run_engine)() as db:
        historical=MetaData()
        progress_table=Table('reading_progress',historical,autoload_with=db.connection())
        history_table=Table('reading_history',historical,autoload_with=db.connection())
        progress=db.execute(select(progress_table)).one();history=db.execute(select(history_table)).one()
        # Inspect the actual historical revision, not today's ORM (which may
        # include columns introduced by later additive migrations).
        historical_runs=Table('reading_runs',MetaData(),autoload_with=db.connection())
        run=db.execute(select(historical_runs)).one()
        UUID(run.run_key)
        assert progress.reading_run_key==history.reading_run_key==run.run_key
        assert progress.revision==7 and progress.position==300 and progress.percent==100
        assert run.ordinal==1 and not run.requires_run_key and run.started_at is None and run.started_at_inferred
        assert run.completed_at is None and run.completed_at_inferred and run.progress_snapshot['revision']==7
        events=db.query(ReadingRunEvent).all();assert {event.kind for event in events}=={'started','completed'}
        assert all(event.inferred and event.occurred_at is None for event in events)
        # Downgrades compact same-day rereads to the prior maximum, preserving
        # the legacy unique key without destroying a stronger completion fact.
        db.execute(history_table.insert().values(user_id=user,novel_id=novel,chapter_number=2,reading_date=history.reading_date,max_percent=50,reading_run_key=str(uuid4())))
        db.commit()
    with run_engine.connect() as connection:
        command.downgrade(alembic_config(connection),'0042');connection.commit()
        assert connection.execute(text('SELECT max_percent FROM reading_history')).scalars().all()==[100]
        assert connection.execute(text('SELECT revision FROM reading_progress')).scalar()==7
    assert 'reading_runs' not in inspect(run_engine).get_table_names()


@pytest.mark.parametrize('same_operation',[False,True])
def test_postgres_start_again_serializes_revision_and_operation_ids(run_engine,same_operation):
    if run_engine.dialect.name!='postgresql':pytest.skip('PostgreSQL row lock qualification')
    upgrade_database(run_engine)
    factory=sessionmaker(bind=run_engine)
    with factory() as db:
        user=User(username='run-race-owner',password='unused');db.add(user);db.flush()
        library=Library(user_id=user.id,name='Private');db.add(library);db.flush()
        novel=Novel(library_id=library.id,title='Concurrent reread');db.add(novel);db.flush()
        chapter=Chapter(novel_id=novel.id,chapter_number=5,title='Actual first',content='Story text');db.add(chapter);db.commit()
        progress=save_reading_progress(db,user_id=user.id,chapter=chapter,position=0,percent=100)
        user_id,novel_id,revision,key=user.id,novel.id,progress.revision,progress.reading_run_key
    barrier=Barrier(2)
    def start(index):
        with factory() as db:
            barrier.wait()
            try:return action(db,user_id,novel_id,ReadingRunAction(expected_revision=revision,reading_run_key=key,operation_id='same' if same_operation else f'device-{index}'),'start')
            except HTTPException as exc:return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as executor:results=list(executor.map(start,[0,1]))
    if same_operation:
        assert isinstance(results[0],dict) and results[0]==results[1]
    else:assert sum(isinstance(result,dict) for result in results)==1 and 409 in results
    with factory() as db:
        assert db.query(ReadingRun).count()==2
        assert db.query(ReadingProgress).one().revision==revision+1
        assert db.query(ReadingRunEvent).filter_by(kind='completed').count()==1
