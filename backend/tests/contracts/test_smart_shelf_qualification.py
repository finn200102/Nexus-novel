"""Independent privacy, query and mutation qualification for private smart shelves."""
# ruff: noqa: F811
from datetime import datetime
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event
from app.models import User,Library,Novel,Chapter,ReadingProgress
from app.models.follow import UserNovelFollow
from app.models.novel_personal import NovelPersonalData,NovelUserTag
from app.models.shelf import Shelf,ShelfNovel
from app.schemas.library_views import OwnedLibraryDefinition
from app.services import library_view_service as views
from tests.routes.conftest import db,test_user,test_library,client,auth_headers  # noqa: F401

@pytest.fixture
def owned_rows(db,test_user,test_library):
    second=Library(name='Second owned library',user_id=test_user.id)
    stranger=User(username='smart-shelf-stranger',password='unused')
    db.add_all([second,stranger]);db.flush()
    foreign=Library(name='Foreign library',user_id=stranger.id);db.add(foreign);db.flush()
    now=datetime(2025,1,1);rows=[]
    for index,library in enumerate([test_library,second,foreign]):
        novel=Novel(library_id=library.id,title='Same title',url=f'https://example.test/{index}',
            author='Owner' if index<2 else 'PRIVATE FOREIGN AUTHOR',created_at=now,updated_at=now,
            chapter_count=10,follow_state='reading')
        db.add(novel);db.flush();rows.append(novel)
    shelf=Shelf(user_id=test_user.id,name='Owned static shelf');foreign_shelf=Shelf(user_id=stranger.id,name='Foreign empty shelf')
    db.add_all([shelf,foreign_shelf]);db.flush()
    db.add_all([ShelfNovel(shelf_id=shelf.id,novel_id=rows[0].id),
        ShelfNovel(shelf_id=shelf.id,novel_id=rows[2].id,added_by_user_id=stranger.id)])
    db.commit()
    return dict(second=second,foreign=foreign,stranger=stranger,rows=rows,shelf=shelf,foreign_shelf=foreign_shelf)

@pytest.mark.parametrize('invalid',[{'unknown':True},{'scope':'catalog'},{'version':True},{'version':1.0},
    {'library_ids':[True]},{'library_ids':['1']},{'library_ids':[0]},{'shelf_id':True},
    {'min_rating':'3'},{'source':'arbitrary-new-source'},{'follow_states':['future']},{'user_tag':'   '}])
def test_definition_never_coerces_or_broadens_unsupported_criteria(invalid):
    with pytest.raises(ValidationError):OwnedLibraryDefinition.model_validate(invalid)

def test_all_owned_libraries_are_dynamic_static_membership_never_grants_foreign_access(db,test_user,owned_rows):
    rows=owned_rows['rows'];result=views.page(db,test_user.id,OwnedLibraryDefinition(sort_by='title'))
    assert [row['id'] for row in result['items']]==[rows[0].id,rows[1].id]
    assert result['total']==result['library_total']==2 and result['status_counts']['reading']==2
    assert 'PRIVATE FOREIGN' not in str(result)
    result=views.page(db,test_user.id,OwnedLibraryDefinition(shelf_id=owned_rows['shelf'].id))
    assert [row['id'] for row in result['items']]==[rows[0].id]
    extra=Novel(library_id=owned_rows['second'].id,title='Newly added',url='nexus-local:epub:new')
    db.add(extra);db.commit();assert views.page(db,test_user.id,{})['total']==3
    db.delete(extra);db.commit();assert views.page(db,test_user.id,{})['total']==2

@pytest.mark.parametrize('criterion',['foreign_library','foreign_empty_shelf','missing_library','missing_shelf'])
def test_empty_or_missing_foreign_filters_fail_closed(db,test_user,owned_rows,criterion):
    criteria={'foreign_library':{'library_ids':[owned_rows['foreign'].id]},
        'foreign_empty_shelf':{'shelf_id':owned_rows['foreign_shelf'].id},
        'missing_library':{'library_ids':[2147483647]},'missing_shelf':{'shelf_id':2147483647}}
    with pytest.raises(HTTPException) as blocked:views.page(db,test_user.id,criteria[criterion])
    assert blocked.value.status_code==404

@pytest.mark.parametrize('sort',['recent','title','chapters','updated_since_read','personal_rating'])
def test_equal_sort_values_have_stable_disjoint_sql_pages(db,test_user,owned_rows,sort):
    definition=OwnedLibraryDefinition(sort_by=sort);whole=views.page(db,test_user.id,definition)['items']
    pages=[views.page(db,test_user.id,definition,offset=i,limit=1)['items'][0] for i in range(2)]
    assert [row['id'] for row in pages]==[row['id'] for row in whole]
    assert len({row['id'] for row in pages})==2

def test_status_counts_ignore_only_selected_status_and_use_owned_personal_fields(db,test_user,owned_rows):
    first,second,_=owned_rows['rows']
    db.add_all([UserNovelFollow(user_id=test_user.id,novel_id=first.id,state='completed'),
        NovelPersonalData(user_id=test_user.id,novel_id=first.id,rating=5),
        NovelPersonalData(user_id=test_user.id,novel_id=second.id,rating=4),
        NovelPersonalData(user_id=owned_rows['stranger'].id,novel_id=second.id,rating=1),
        NovelUserTag(user_id=test_user.id,novel_id=first.id,tag='chosen'),
        NovelUserTag(user_id=owned_rows['stranger'].id,novel_id=second.id,tag='chosen')]);db.commit()
    result=views.page(db,test_user.id,{'min_rating':4,'follow_states':['reading']})
    assert [row['id'] for row in result['items']]==[second.id] and result['items'][0]['personal_rating']==4
    assert result['total']==1 and result['library_total']==2
    assert result['status_counts']['reading']==result['status_counts']['completed']==1
    assert views.page(db,test_user.id,{'user_tag':' CHOSEN '})['items'][0]['id']==first.id
    assert views.options(db,test_user.id)['user_tags']==['chosen']

def test_local_queries_escape_wildcards_and_never_load_bodies_or_enrich_metadata(db,test_user,owned_rows,monkeypatch):
    from app.services import metadata_client
    first=owned_rows['rows'][0];first.title=r'Literal 50%_\ text';first.metadata_id=123
    db.add(Chapter(novel_id=first.id,chapter_number=0,content='PRIVATE ORIGINAL '*1000,document={'private':'never load'}))
    db.add(ReadingProgress(user_id=test_user.id,novel_id=first.id,chapter_number=-1,position=0,percent=0));db.commit()
    def forbidden(*args,**kwargs):raise AssertionError('Local query attempted external enrichment')
    monkeypatch.setattr(metadata_client,'get_novel_metadata',forbidden)
    statements=[]
    def capture(connection,cursor,statement,parameters,context,many):statements.append(statement.lower())
    event.listen(db.bind,'before_cursor_execute',capture)
    try:result=views.page(db,test_user.id,{'q':'50%_' + chr(92),'sort_by':'updated_since_read'})
    finally:event.remove(db.bind,'before_cursor_execute',capture)
    assert [row['id'] for row in result['items']]==[first.id]
    assert len(statements)<=6
    assert not any('chapters.content' in sql or 'chapters.document' in sql or 'select chapters.' in sql for sql in statements)

@pytest.fixture
def pg_shelves():
    import os
    from uuid import uuid4
    from sqlalchemy import create_engine,text
    from sqlalchemy.orm import sessionmaker
    from config.database import Base
    url=os.environ.get('NEXUS_TEST_POSTGRES_URL')
    if not url:pytest.skip('Requires the owned disposable PostgreSQL instance')
    schema='smart_shelf_qualification_'+uuid4().hex
    admin=create_engine(url);engine=None
    try:
        with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
        Base.metadata.create_all(engine);factory=sessionmaker(bind=engine)
        with factory() as session:
            owner=User(username='pg-smart-owner',password='unused');session.add(owner);session.flush()
            library=Library(user_id=owner.id,name='PG shelf library');session.add(library);session.flush()
            for n in range(3):
                novel=Novel(library_id=library.id,title='Equal title',url=f'nexus-local:epub:{n}',
                    created_at=datetime(2025,1,1),updated_at=datetime(2025,1,1),chapter_count=3)
                session.add(novel)
            session.commit();info=dict(user_id=owner.id,library_id=library.id)
        yield factory,info
    finally:
        if engine is not None:engine.dispose()
        with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
        admin.dispose()


def test_postgres_actual_local_options_filters_counts_and_all_sort_projections(pg_shelves):
    factory,info=pg_shelves
    with factory() as session:
        result=views.options(session,info['user_id'])
        assert result['sources']==[{'id':'local','label':'Local EPUB'}]
        assert result['libraries']==[{'id':info['library_id'],'name':'PG shelf library'}]
        for sort in ('recent','title','chapters','updated_since_read','personal_rating'):
            result=views.page(session,info['user_id'],{'source':'local','sort_by':sort},limit=1)
            assert result['total']==result['library_total']==3
            assert result['status_counts']['plan_to_read']==3 and len(result['items'])==1


def make_smart(db,user_id,name='Quiet shelf',definition=None):
    from app.schemas.smart_shelf import SmartShelfWrite
    from app.services import smart_shelf_service as smart
    return smart.create(db,user_id,SmartShelfWrite(name=name,definition=definition or {}))


def test_unicode_case_and_space_name_uniqueness_and_foreign_isolation(db,test_user,owned_rows):
    from app.schemas.smart_shelf import SmartShelfUpdate
    from app.services import smart_shelf_service as smart
    first=make_smart(db,test_user.id,' Straße   Notes ')
    assert first['name']=='Straße Notes'
    with pytest.raises(HTTPException) as duplicate:make_smart(db,test_user.id,'STRASSE notes')
    assert duplicate.value.status_code==409
    foreign=make_smart(db,owned_rows['stranger'].id,'STRASSE notes')
    assert foreign['id']!=first['id']
    for action in ('results','edit','delete'):
        with pytest.raises(HTTPException) as denied:
            if action=='results':smart.results(db,owned_rows['stranger'].id,first['id'])
            elif action=='delete':smart.delete(db,owned_rows['stranger'].id,first['id'],first['revision'])
            else:smart.update(db,owned_rows['stranger'].id,first['id'],SmartShelfUpdate(name='Stolen',definition={},expected_revision=first['revision']))
        assert denied.value.status_code==404;db.rollback()


def test_definition_aba_and_stale_delete_cannot_replay_old_revision(db,test_user):
    from app.schemas.smart_shelf import SmartShelfUpdate
    from app.services import smart_shelf_service as smart
    first=make_smart(db,test_user.id)
    second=smart.update(db,test_user.id,first['id'],SmartShelfUpdate(name=first['name'],definition={'q':'Different'},expected_revision=first['revision']))
    third=smart.update(db,test_user.id,first['id'],SmartShelfUpdate(name=first['name'],definition={},expected_revision=second['revision']))
    assert len({first['revision'],second['revision'],third['revision']})==3
    with pytest.raises(HTTPException) as stale:smart.delete(db,test_user.id,first['id'],first['revision'])
    assert stale.value.status_code==409;db.rollback()
    assert smart.results(db,test_user.id,first['id'])['definition_revision']==third['revision']


@pytest.mark.parametrize('kind',['library','shelf'])
def test_reused_numeric_parent_id_never_reactivates_old_bound_query(db,test_user,owned_rows,kind):
    from app.services import smart_shelf_service as smart
    from sqlalchemy import delete
    user_id=test_user.id
    model=Library if kind=='library' else Shelf
    old=owned_rows['second'] if kind=='library' else owned_rows['shelf']
    old_id=old.id;name=old.name
    definition={'library_ids':[old_id]} if kind=='library' else {'shelf_id':old_id}
    saved=make_smart(db,user_id,definition=definition)
    original_identity=old.identity_key
    db.execute(delete(model).where(model.id==old_id));db.commit();db.expunge_all()
    replacement=model(id=old_id,user_id=user_id,name=name)
    db.add(replacement);db.commit()
    assert replacement.identity_key!=original_identity
    with pytest.raises(HTTPException) as blocked:smart.results(db,user_id,saved['id'])
    assert blocked.value.status_code==409 and blocked.value.detail['code']=='smart_shelf_review_required';db.rollback()
    from app.models import SmartShelf
    shown=smart.present(db,db.get(SmartShelf,saved['id']))
    assert shown['needs_review'] and shown['definition'] is not None


def pg_race(factory,actions):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    barrier=Barrier(len(actions))
    def perform(action):
        with factory() as session:
            barrier.wait(timeout=15)
            try:return 200,action(session)
            except HTTPException as exc:session.rollback();return exc.status_code,exc.detail
    with ThreadPoolExecutor(max_workers=len(actions)) as pool:return list(pool.map(perform,actions))


def test_postgres_concurrent_unicode_create_and_same_revision_update(pg_shelves):
    from app.schemas.smart_shelf import SmartShelfUpdate
    from app.services import smart_shelf_service as smart
    factory,info=pg_shelves;owner=info['user_id']
    results=pg_race(factory,[lambda db:make_smart(db,owner,'Straße'),lambda db:make_smart(db,owner,'STRASSE')])
    assert sorted(code for code,_ in results)==[200,409]
    first=next(value for code,value in results if code==200)
    def update(session,q):return smart.update(session,owner,first['id'],SmartShelfUpdate(name=first['name'],definition={'q':q},expected_revision=first['revision']))
    results=pg_race(factory,[lambda db:update(db,'Left'),lambda db:update(db,'Right')])
    assert sorted(code for code,_ in results)==[200,409]
    winner=next(value for code,value in results if code==200)
    with factory() as session:
        final=smart.results(session,owner,first['id'])
        assert final['definition_revision']==winner['revision']


def test_account_purge_removes_only_owned_smart_definitions_even_with_sqlite_fk_off(db,test_user,monkeypatch):
    from app.models import SmartShelf
    from app.services import account_service,audio_export_service,podcast_audio_service
    other=User(username='smart-purge-other',password='unused');db.add(other);db.commit()
    owner_id=test_user.id;other_id=other.id
    own=make_smart(db,owner_id,'Private owner rule');foreign=make_smart(db,other_id,'Private other rule')
    monkeypatch.setattr(account_service,'_user_disk_files',lambda *_:[])
    monkeypatch.setattr(account_service,'_user_download_dirs',lambda *_:[])
    monkeypatch.setattr(audio_export_service,'purge_export_files',lambda *_:None)
    monkeypatch.setattr(podcast_audio_service,'purge_podcast_audio_files',lambda *_:None)
    account_service.delete_user_account(db,db.get(User,owner_id))
    db.expire_all()
    assert db.get(SmartShelf,own['id']) is None
    assert db.get(SmartShelf,foreign['id']).user_id==other_id


def test_real_http_contract_requires_delete_cas_and_never_fetches_legacy_blank_title(client,db,test_user,owned_rows,auth_headers,monkeypatch):
    from app.services import metadata_client
    first=owned_rows['rows'][0];first.title='';first.url=None;first.metadata_id=98765;db.commit()
    def forbidden(*args,**kwargs):raise AssertionError('Private shelf read attempted metadata RPC')
    monkeypatch.setattr(metadata_client,'get_novel_metadata',forbidden)
    created=client.post('/smart-shelves',headers=auth_headers,json={'name':'HTTP shelf','definition':{}})
    assert created.status_code==201,created.text
    assert created.headers['cache-control']=='private, no-store'
    row=created.json();url=f"/smart-shelves/{row['id']}"
    result=client.post(url+'/results',headers=auth_headers,json={'limit':100})
    assert result.status_code==200,result.text
    assert result.json()['definition_revision']==row['revision'] and result.json()['total']==2
    legacy=next(item for item in result.json()['items'] if item['id']==first.id)
    assert legacy['title']=='' and legacy['url'] is None
    assert result.headers['cache-control']=='private, no-store'
    assert client.delete(url,headers=auth_headers).status_code==422
    assert client.post(url+'/results',headers=auth_headers,json={'offset':True}).status_code==422
    assert client.post('/library-views/preview',headers=auth_headers,json={'definition':{'library_ids':[owned_rows['foreign'].id]}}).status_code==404
    assert client.get('/smart-shelves').status_code==401
    assert client.delete(url,headers=auth_headers,params={'expected_revision':row['revision']}).json()=={'deleted':True}


def test_postgres_reviewed_edit_and_delete_are_serialized(pg_shelves):
    from app.schemas.smart_shelf import SmartShelfUpdate
    from app.services import smart_shelf_service as smart
    from app.models import SmartShelf
    factory,info=pg_shelves;owner=info['user_id']
    with factory() as session:first=make_smart(session,owner)
    def edit(session):return smart.update(session,owner,first['id'],SmartShelfUpdate(name='Changed',definition={},expected_revision=first['revision']))
    results=pg_race(factory,[edit,lambda db:smart.delete(db,owner,first['id'],first['revision'])])
    assert [code for code,_ in results] in ([200,409],[404,200])
    with factory() as session:
        row=session.get(SmartShelf,first['id'])
        if row is not None:assert row.name=='Changed' and row.revision!=first['revision']
        else:assert results[1][1]=={'deleted':True}


def portable_import(db,user_id,value):
    from app.schemas.user_data import ExportSmartShelf
    from app.services import smart_shelf_portable_service as portable
    reports=portable.import_rows(db,user_id,[ExportSmartShelf.model_validate(value)])
    db.commit()
    return reports[0]


@pytest.mark.parametrize('scope',['all','named'])
def test_portable_roundtrip_resolves_only_owned_names_and_is_idempotent(db,test_user,owned_rows,scope):
    from app.services import smart_shelf_portable_service as portable
    from app.services import smart_shelf_service as smart
    from app.models import SmartShelf
    definition={} if scope=='all' else {'library_ids':[owned_rows['second'].id],'shelf_id':owned_rows['shelf'].id}
    source=make_smart(db,test_user.id,'Portable match',definition)
    exported=portable.export_rows(db,test_user.id)[0]
    assert 'library_ids' not in exported['definition'] and 'shelf_id' not in exported['definition']
    assert 'identity' not in str(exported) and source['revision'] not in str(exported)
    destination=User(username='portable-destination',password='unused');db.add(destination);db.flush();destination_id=destination.id
    library=Library(name=owned_rows['second'].name,user_id=destination_id)
    shelf=Shelf(name=owned_rows['shelf'].name,user_id=destination_id)
    db.add_all([library,shelf]);db.commit()
    report=portable_import(db,destination_id,exported)
    assert report['status']=='created' and not report['needs_review']
    row=db.query(SmartShelf).filter_by(user_id=destination_id).one()
    if scope=='named':assert row.definition['library_ids']==[library.id] and row.definition['shelf_id']==shelf.id
    else:assert row.definition['library_ids']==[]
    assert not smart.present(db,row)['needs_review']
    assert portable_import(db,destination_id,exported)['status']=='unchanged'


@pytest.mark.parametrize('criteria',[{'libraries':[]},{'libraries':['Missing library']},
    {'libraries':['Foreign library']},{'static_shelf':'Foreign empty shelf'},
    {'definition':{'library_ids':[1]}},{'definition':{'unsupported_future_rule':True}}])
def test_unresolved_portable_rules_stay_review_required_without_broadening(db,test_user,owned_rows,criteria):
    from app.models import SmartShelf
    from app.services import smart_shelf_portable_service as portable,smart_shelf_service as smart
    value={'name':'Needs explicit review','definition':{},'libraries':None,'static_shelf':None,**criteria}
    report=portable_import(db,test_user.id,value)
    assert report['status']=='created' and report['needs_review']
    row=db.query(SmartShelf).filter_by(user_id=test_user.id).one()
    assert smart.present(db,row)['needs_review']
    with pytest.raises(HTTPException) as blocked:smart.results(db,test_user.id,row.id)
    assert blocked.value.status_code==409;db.rollback()
    reexport=portable.export_rows(db,test_user.id)[0]
    assert reexport['needs_review'] and reexport['definition']==value['definition']
    assert portable_import(db,test_user.id,value)['status']=='unchanged'


def test_portable_export_uses_current_parent_names_after_safe_identity_preserving_rename(db,test_user,owned_rows):
    from app.services import smart_shelf_portable_service as portable
    definition={'library_ids':[owned_rows['second'].id],'shelf_id':owned_rows['shelf'].id}
    make_smart(db,test_user.id,definition=definition)
    owned_rows['second'].name='Renamed library';owned_rows['shelf'].name='Renamed static shelf';db.commit()
    result=portable.export_rows(db,test_user.id)[0]
    assert not result['needs_review']
    assert result['libraries']==['Renamed library'] and result['static_shelf']=='Renamed static shelf'


def test_saved_membership_recomputes_after_personal_tag_changes_without_definition_edit(db,test_user,owned_rows):
    from app.services import smart_shelf_service as smart
    first,second,_=owned_rows['rows']
    tag=NovelUserTag(user_id=test_user.id,novel_id=first.id,tag='dynamic');db.add(tag);db.commit()
    rule=make_smart(db,test_user.id,definition={'user_tag':'dynamic'})
    assert [row['id'] for row in smart.results(db,test_user.id,rule['id'])['items']]==[first.id]
    tag.novel_id=second.id;db.commit()
    current=smart.results(db,test_user.id,rule['id'])
    assert [row['id'] for row in current['items']]==[second.id]
    assert current['definition_revision']==rule['revision']


def test_portable_conflict_retains_local_reviewed_definition_and_revision(db,test_user):
    from app.models import SmartShelf
    local=make_smart(db,test_user.id,definition={'q':'Keep private current choice'})
    result=portable_import(db,test_user.id,{'name':local['name'],'definition':{'q':'Imported replacement'}})
    assert result['status']=='conflict'
    row=db.get(SmartShelf,local['id'])
    assert row.definition['q']=='Keep private current choice' and row.revision==local['revision']
