"""Independent saved-query checkpoint/race/migration qualification."""
import os
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import datetime
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine,text,MetaData
from sqlalchemy.orm import sessionmaker
from alembic import command
from config.database import Base
from app.db_migrations import alembic_config
from app.models import User
from app.models.saved_search import SavedSearch
from app.models.catalog_watch import CatalogWatch,CatalogWatchSeen,CatalogMatch
from app.models.update_event import NovelUpdateEvent
from app.services import catalog_watch_service as svc
from app.services.saved_search_service import revision
from tests.routes.test_catalog_watches import search,prepared,baseline,activate,claim,events


@pytest.fixture(params=['sqlite','postgres'])
def engine(request,tmp_path):
    if request.param=='sqlite':
        target=create_engine(f'sqlite:///{tmp_path}/watch.db');yield target;target.dispose();return
    url=os.getenv('NEXUS_TEST_POSTGRES_URL')
    if not url:pytest.skip('Requires owned disposable PostgreSQL')
    schema='watch_qualification_'+uuid4().hex;admin=create_engine(url)
    with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
    target=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
    try:yield target
    finally:
        target.dispose()
        with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
        admin.dispose()


@pytest.fixture
def data(engine):
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine,expire_on_commit=False)() as db:
        user=User(username='independent-watcher',password='unused');db.add(user);db.commit()
        row=search(db,user);watch,_=prepared(db,user,row)
        yield db,user,row,watch


@pytest.mark.parametrize('kind',['same_page','repeated_page','backward_page'])
def test_baseline_counts_only_unique_advancing_snapshot_keys(data,kind):
    db,user,row,watch=data
    keys=sorted([str(uuid4()),str(uuid4())])
    if kind=='same_page':
        with pytest.raises(HTTPException):activate(db,user,row,watch,baseline(watch,[keys[0],keys[0]],total=2))
        db.rollback()
        assert db.query(CatalogWatchSeen).count()==0
    else:
        first=baseline(watch,[keys[1]],total=2,more=True)
        activate(db,user,row,watch,first);snap,token=claim(db)
        key=keys[1] if kind=='repeated_page' else keys[0]
        with pytest.raises(HTTPException):svc.finish_worker(db,snap,token,baseline(watch,[key],total=2,snapshot_id=first['snapshot_id']))
        db.rollback()
        fresh=db.query(CatalogWatch).populate_existing().one()
        assert fresh.status=='initializing' and fresh.baseline_offset==1
        assert db.query(CatalogWatchSeen).count()==1
    assert db.query(NovelUpdateEvent).count()==0


def test_invalid_later_event_rolls_back_match_receipts_and_cursor_together(data):
    db,user,row,watch=data;activate(db,user,row,watch);snap,token=claim(db)
    page=events(watch,[str(uuid4()),str(uuid4())]);page['matches'][1]['seq']=999
    with pytest.raises(HTTPException):svc.finish_worker(db,snap,token,page)
    db.rollback()
    fresh=db.query(CatalogWatch).populate_existing().one()
    assert fresh.cursor==10 and db.query(CatalogWatchSeen).count()==0
    assert db.query(CatalogMatch).count()==0 and db.query(NovelUpdateEvent).count()==0


def test_future_deletion_cannot_erase_current_match_or_advance_checkpoint(data):
    db,user,row,watch=data;activate(db,user,row,watch);key=str(uuid4());snap,token=claim(db)
    svc.finish_worker(db,snap,token,events(watch,[key]))
    watch.next_check_at=None;db.commit();snap,token=claim(db)
    page=events(watch,through=21,deleted=[{'work_key':key,'seq':999,'novel_id':22}])
    with pytest.raises(HTTPException):svc.finish_worker(db,snap,token,page)
    db.rollback()
    assert db.query(CatalogMatch).one().work_key==key and db.query(NovelUpdateEvent).one().notification_visible
    assert db.query(CatalogWatch).populate_existing().one().cursor==20


def test_hybrid_union_capacity_is_1200_and_no_hidden_truncation(data):
    db,user,row,watch=data;activate(db,user,row,watch);snap,token=claim(db)
    page=events(watch,[str(uuid4()) for _ in range(1200)])
    assert svc.finish_worker(db,snap,token,page)
    assert db.query(CatalogMatch).count()==1200 and db.query(NovelUpdateEvent).count()==1200


def test_visibility_changed_in_other_session_blocks_stale_worker_snapshot(data,engine):
    db,user,row,watch=data;activate(db,user,row,watch)
    claimed=svc.claim(db)
    # Keep stale ORM objects alive; server guards must populate_existing.
    assert user.is_disabled is False
    with sessionmaker(bind=engine)() as other:
        current=other.get(User,user.id);current.is_disabled=True;other.commit()
    assert svc.worker_snapshot(db,*claimed) is None
    assert db.query(CatalogWatch).populate_existing().one().status=='paused'


def test_pause_then_new_prepare_fences_old_worker_without_pausing_new_state(data):
    db,user,row,watch=data;state=activate(db,user,row,watch);old,token=claim(db)
    svc.pause(db,user.id,row.id,revision(row),state['revision'])
    newer,_=prepared(db,user,row)
    assert newer.status=='prepared'
    assert svc.worker_snapshot(db,newer.id,token) is None
    assert svc.finish_worker(db,old,token,events(newer,[str(uuid4())])) is False
    assert db.query(CatalogWatch).populate_existing().one().status=='prepared'


def test_account_namespace_change_rejects_old_inflight_checkpoint(data,engine):
    db,user,row,watch=data;activate(db,user,row,watch);snap,token=claim(db)
    with sessionmaker(bind=engine)() as other:
        current=other.get(User,user.id);current.storage_id=str(uuid4());other.commit()
    assert svc.finish_worker(db,snap,token,events(watch,[str(uuid4())])) is False
    assert db.query(CatalogMatch).count()==0


def test_actual_postgres_concurrent_claim_and_same_receipt_commit(data,engine):
    if engine.dialect.name!='postgresql':pytest.skip('Real row-lock race requires PostgreSQL')
    db,user,row,watch=data;activate(db,user,row,watch);factory=sessionmaker(bind=engine)
    def race(operation):
        barrier=Barrier(2)
        def one(_):
            with factory() as connection:
                barrier.wait(timeout=5)
                return operation(connection)
        with ThreadPoolExecutor(max_workers=2) as pool:return list(pool.map(one,range(2)))
    outcomes=race(svc.claim)
    assert sum(value is not None for value in outcomes)==1
    claim_value=next(value for value in outcomes if value)
    snap=svc.worker_snapshot(db,*claim_value)
    results=race(lambda connection:svc.finish_worker(connection,snap,claim_value[1],events(watch,[str(uuid4())])))
    assert sorted(results)==[False,True]
    assert db.query(CatalogMatch).count()==1 and db.query(NovelUpdateEvent).count()==1


def test_0047_to_0048_preserves_legacy_flag_without_enabling_watch(engine):
    with engine.begin() as connection:command.upgrade(alembic_config(connection),'0047')
    old=MetaData();old.reflect(engine)
    with engine.begin() as connection:
        uid=connection.execute(old.tables['users'].insert().values(username='legacy-watch',password='unused',storage_id=str(uuid4()))).inserted_primary_key[0]
        sid=connection.execute(old.tables['saved_searches'].insert().values(user_id=uid,name='Original',filters={'tag':['magic']},notify_on_match=True,created_at=datetime(2020,1,1),updated_at=datetime(2020,1,1))).inserted_primary_key[0]
    with engine.begin() as connection:command.upgrade(alembic_config(connection),'0048')
    current=MetaData();current.reflect(engine)
    with engine.connect() as connection:
        row=connection.execute(current.tables['saved_searches'].select()).mappings().one()
        assert row['id']==sid and row['name']=='Original' and row['notify_on_match'] is True and len(row['identity_key'])==36
        assert connection.execute(current.tables['catalog_watches'].select()).all()==[]
    with engine.begin() as connection:command.downgrade(alembic_config(connection),'0047')
    restored=MetaData();restored.reflect(engine)
    assert 'identity_key' not in restored.tables['saved_searches'].c


def test_invalid_query_state_counts_agree_with_match_page_but_valid_pause_keeps_history(data):
    db,user,row,watch=data;state=activate(db,user,row,watch);snap,token=claim(db)
    svc.finish_worker(db,snap,token,events(watch,[str(uuid4())]))
    svc.pause(db,user.id,row.id,revision(row),state['revision'])
    assert svc.state(db,user.id,row.id)['match_count']==1
    assert svc.matches(db,user.id,row.id,0,50)['total']==1
    row.name='Changed saved query';row.updated_at=datetime(2030,1,1);db.commit()
    assert svc.state(db,user.id,row.id)['match_count']==0
    assert svc.matches(db,user.id,row.id,0,50)['total']==0


def test_actual_postgres_stale_snapshot_cannot_pause_new_preparation(data,engine):
    if engine.dialect.name!='postgresql':pytest.skip('Real concurrent snapshot needs PostgreSQL')
    from threading import Event,get_ident
    from sqlalchemy import event
    db,user,row,watch=data;activate(db,user,row,watch);old_claim=svc.claim(db)
    loaded=Event();resume=Event();worker_thread=[];factory=sessionmaker(bind=engine)
    def pause_after_initial_read(conn,cursor,statement,params,context,many):
        if worker_thread and get_ident()==worker_thread[0] and not loaded.is_set() and 'FROM catalog_watches' in statement:
            loaded.set();assert resume.wait(5)
    event.listen(engine,'after_cursor_execute',pause_after_initial_read)
    def old_worker():
        worker_thread.append(get_ident())
        with factory() as session:return svc.worker_snapshot(session,*old_claim)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            result=pool.submit(old_worker);assert loaded.wait(5)
            row.filters={'version':1,'scope':'catalog','q':'new reviewed query','filters':{}}
            row.updated_at=datetime(2030,1,1);db.commit()
            newer,state=prepared(db,user,row)
            new_revision=state['revision']
            resume.set()
            assert result.result(timeout=5) is None
        actual=db.query(CatalogWatch).populate_existing().one()
        assert actual.status=='prepared' and actual.revision==new_revision
    finally:
        resume.set();event.remove(engine,'after_cursor_execute',pause_after_initial_read)


def test_match_paging_streams_payloads_and_reads_hidden_rules_once(data,monkeypatch):
    db,user,row,watch=data;activate(db,user,row,watch);snap,token=claim(db)
    svc.finish_worker(db,snap,token,events(watch,[str(uuid4()) for _ in range(130)]))
    from sqlalchemy.orm import Query
    original_all=Query.all
    def no_match_all(query):
        if any(description.get('entity') is CatalogMatch for description in query.column_descriptions):
            raise AssertionError('Match metadata must be streamed, not materialized all at once')
        return original_all(query)
    monkeypatch.setattr(Query,'all',no_match_all)
    blocked=svc.blocked_values;calls=[]
    monkeypatch.setattr(svc,'blocked_values',lambda *args:calls.append(1) or blocked(*args))
    page=svc.matches(db,user.id,row.id,100,20)
    assert page['total']==130 and len(page['items'])==20 and page['has_more']
    assert len(calls)==1
    calls.clear();state=svc.state(db,user.id,row.id)
    assert state['match_count']==130 and state['unread_count']==130 and len(calls)==1
