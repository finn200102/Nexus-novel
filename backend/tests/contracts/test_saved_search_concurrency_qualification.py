"""Independent real-PostgreSQL qualification of saved-search edit fences."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4
import os
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine,text
from sqlalchemy.orm import sessionmaker
from config.database import Base
from app.models import User,SavedSearch
from app.routers.saved_search import create_saved_search,update_saved_search,delete_saved_search
from app.schemas.saved_search import SavedSearchWrite,SavedSearchUpdate
from app.services.saved_search_service import revision,decode,imported,present


@pytest.fixture
def pg_searches():
    url=os.environ.get('NEXUS_TEST_POSTGRES_URL')
    if not url:pytest.skip('Requires an owned disposable PostgreSQL database')
    schema='saved_search_qualification_'+uuid4().hex
    admin=create_engine(url);engine=None
    try:
        with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
        Base.metadata.create_all(engine)
        factory=sessionmaker(bind=engine)
        with factory() as db:
            owner=User(username='search-owner',password='unused');foreign=User(username='foreign-search-owner',password='unused')
            db.add_all([owner,foreign]);db.flush()
            item=SavedSearch(user_id=owner.id,name='Original',filters={'version':1,'scope':'catalog','q':'Original exact query','filters':{'excludeTag':['Forbidden']}})
            db.add(item);db.commit()
            info={'owner':owner.id,'foreign':foreign.id,'id':item.id,'revision':revision(item)}
        yield factory,info
    finally:
        if engine is not None:engine.dispose()
        with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
        admin.dispose()


def run_race(factory,actions):
    barrier=Barrier(len(actions))
    def writer(action):
        with factory() as db:
            barrier.wait(timeout=15)
            try:return action(db)
            except HTTPException as exc:db.rollback();return exc.status_code,exc.detail
    with ThreadPoolExecutor(max_workers=len(actions)) as pool:return list(pool.map(writer,actions))


def edit(db,info,text_value):
    user=db.get(User,info['owner'])
    value=SavedSearchUpdate(name='Original',expected_revision=info['revision'],definition={'q':text_value,'filters':{'excludeTag':['Forbidden']}})
    return 200,update_saved_search(info['id'],value,db,user)


def test_same_revision_concurrent_edits_one_wins_one_conflicts(pg_searches):
    factory,info=pg_searches
    results=run_race(factory,[lambda db:edit(db,info,'Left reader choice'),lambda db:edit(db,info,'Right reader choice')])
    assert sorted(code for code,_ in results)==[200,409]
    success=next(value for code,value in results if code==200)
    failure=next(value for code,value in results if code==409)
    assert failure['code']=='saved_search_changed'
    with factory() as db:
        row=db.get(SavedSearch,info['id'])
        assert present(row)['definition']['q']==success['definition']['q']
        assert revision(row)==success['revision'] and revision(row)!=info['revision']
        assert present(row)['definition']['filters']['excludeTag']==['Forbidden']


def test_conditional_delete_cannot_remove_concurrent_reviewed_edit(pg_searches):
    factory,info=pg_searches
    def remove(db):return 200,delete_saved_search(info['id'],expected_revision=info['revision'],db=db,current_user=db.get(User,info['owner']))
    results=run_race(factory,[lambda db:edit(db,info,'Edited while another reader deletes'),remove])
    assert [code for code,_ in results] in ([200,409],[404,200])
    with factory() as db:
        row=db.get(SavedSearch,info['id'])
        if row is not None:assert row.filters['q']=='Edited while another reader deletes'
        else:assert results[1][1]=={'deleted':True}


def test_duplicate_create_race_keeps_exactly_one_owned_definition(pg_searches):
    factory,info=pg_searches
    def create(db,q):
        value=SavedSearchWrite(name='Same new name',definition={'q':q,'filters':{'excludeFandom':['No spoilers']}})
        return 201,create_saved_search(value,db,db.get(User,info['owner']))
    results=run_race(factory,[lambda db:create(db,'Left exact choice'),lambda db:create(db,'Right exact choice')])
    assert sorted(code for code,_ in results)==[201,409]
    success=next(value for code,value in results if code==201)
    with factory() as db:
        rows=db.query(SavedSearch).filter_by(user_id=info['owner'],name='Same new name').all()
        assert len(rows)==1 and rows[0].filters['q']==success['definition']['q']


def test_foreign_edit_delete_and_replayed_stale_edit_stay_fenced(pg_searches):
    factory,info=pg_searches
    with factory() as db:
        for action in ('update','delete'):
            with pytest.raises(HTTPException) as blocked:
                if action=='update':update_saved_search(info['id'],SavedSearchUpdate(name='Foreign replacement',definition={'q':'steal'},expected_revision=info['revision']),db,db.get(User,info['foreign']))
                else:delete_saved_search(info['id'],expected_revision=info['revision'],db=db,current_user=db.get(User,info['foreign']))
            assert blocked.value.status_code==404;db.rollback()
        code,first=edit(db,info,'First acknowledged edit')
        with pytest.raises(HTTPException) as blocked:edit(db,info,'Different unacknowledged retry')
        assert blocked.value.status_code==409;db.rollback()
        assert present(db.get(SavedSearch,info['id']))['revision']==first['revision']


@pytest.mark.parametrize('criteria',[{'unknownFutureRule':'strict'},{'version':3,'scope':'catalog','filters':{'tag':['Keep']}},
    {'version':1,'scope':'private-imported','q':'Keep'},{'version':1,'scope':'catalog','filters':{'excludeNovelIds':[1]}},
    {'version':1,'scope':'catalog','filters':{'minWordCount':-1}}])
def test_unknown_criteria_cannot_decode_to_broad_executable_search(criteria):
    definition,needs_review,warnings=decode(criteria)
    assert definition is None and needs_review and warnings


def test_imported_similarity_stays_unresolved_across_repeated_export_import():
    raw={'version':1,'scope':'catalog','q':'Keep exact text','similar_to':123,'filters':{'excludeTag':['Keep exclusion']}}
    rewritten=imported(raw)
    assert rewritten['unresolved_similarity']=={'previous_catalog_id':123} and 'similar_to' not in rewritten
    definition,needs_review,warnings=decode(rewritten)
    assert definition.similar_to is None and definition.filters.excludeTag==['Keep exclusion'] and definition.q=='Keep exact text'
    assert needs_review and warnings and imported(rewritten)==rewritten


def test_sqlite_aba_roundtrip_cannot_restore_old_revision_under_frozen_database_clock():
    from sqlalchemy.pool import StaticPool
    engine=create_engine('sqlite://',poolclass=StaticPool)
    try:
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as db:
            db.connection().connection.driver_connection.create_function('current_timestamp',0,lambda:'2026-01-01 00:00:00')
            user=User(username='sqlite-aba-owner',password='unused');db.add(user);db.commit()
            initial=create_saved_search(SavedSearchWrite(name='Original',definition={'q':'Original'}),db,user)
            first=update_saved_search(initial['id'],SavedSearchUpdate(name='Changed',definition={'q':'Changed'},expected_revision=initial['revision']),db,user)
            restored=update_saved_search(initial['id'],SavedSearchUpdate(name='Original',definition=initial['definition'],expected_revision=first['revision']),db,user)
            assert restored['revision']!=initial['revision']
            assert restored['updated_at']>initial['updated_at']
            for action in ('edit','delete'):
                with pytest.raises(HTTPException) as blocked:
                    if action=='edit':update_saved_search(initial['id'],SavedSearchUpdate(name='Stale',definition={'q':'Stale'},expected_revision=initial['revision']),db,user)
                    else:delete_saved_search(initial['id'],expected_revision=initial['revision'],db=db,current_user=user)
                assert blocked.value.status_code==409;db.rollback()
            assert db.get(SavedSearch,initial['id']).name=='Original'
    finally:engine.dispose()


@pytest.mark.parametrize('value',[True,1.0,'1',None,3])
def test_unsupported_version_type_never_reinterpreted_as_v1(value):
    from pydantic import ValidationError
    from app.schemas.saved_search import SavedSearchDefinition
    with pytest.raises(ValidationError):SavedSearchDefinition.model_validate({'version':value,'filters':{'tag':['Keep exclusion']}})
