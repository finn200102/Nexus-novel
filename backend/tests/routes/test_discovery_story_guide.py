"""Every shared-guide read/action carries exact, account-private read proof."""
from datetime import datetime
import hashlib
from unittest.mock import AsyncMock,patch
from uuid import uuid4
import pytest
from app.models import Chapter,Novel,ReadingRun,ReadingHistory,ReadingProgress,ChapterReadReceipt
from app.models.chapter import ContentStatus
from app.services.chapter_document import from_text
from app.services.reading_run_service import snapshot_progress


def owned_scope(db,user,library,metadata_id=701,numbers=(1,2,3,4,5),percent=100):
    novel=Novel(title='Verified guide',url=f'https://fixture.invalid/story/{metadata_id}',metadata_id=metadata_id,library_id=library.id)
    db.add(novel);db.flush();chapters=[]
    run=ReadingRun(user_id=user.id,novel_id=novel.id,run_key=str(uuid4()),ordinal=1,status='active',requires_run_key=True,progress_snapshot={})
    db.add(run);db.flush()
    for number in numbers:
        document=from_text(f'Private permitted chapter {number} has uniquely matching text.')
        chapter=Chapter(novel_id=novel.id,chapter_number=number,title=str(number),content=document['plain_text'],document=document,content_status=ContentStatus.PRESENT)
        db.add(chapter);db.flush();db.refresh(chapter);chapters.append(chapter)
        progress=percent if number==numbers[-1] else 100
        db.add(ReadingHistory(user_id=user.id,novel_id=novel.id,chapter_number=number,chapter_key=chapter.chapter_key,
            verified_content_version=document['content_version'],verified_percent=progress,
            reading_run_key=run.run_key,reading_date=datetime(2026,1,1),max_percent=progress))
        db.add(ChapterReadReceipt(user_id=user.id,chapter_id=chapter.id,content_version=document['content_version'],completed=True,requires_review=False))
    point=ReadingProgress(user_id=user.id,novel_id=novel.id,chapter_id=chapters[-1].id,chapter_number=numbers[-1],percent=percent,
        chapter_key=chapters[-1].chapter_key,furthest_chapter_key=chapters[-1].chapter_key,
        source_content_version=chapters[-1].document['content_version'],furthest_content_version=chapters[-1].document['content_version'],
        furthest_chapter_number=numbers[-1],furthest_percent=percent,reading_run_key=run.run_key,revision=9,position=0)
    db.add(point);db.flush();run.progress_snapshot=snapshot_progress(run,point);db.commit()
    return novel,chapters,run,point


@pytest.mark.parametrize('path,operation,args',[
    ('','guide',{}),('/entities','entities',{}),('/relationships','relationships',{}),('/projection','projection',{}),
    ('/changes?from_chapter=2','changes',{'from_chapter':2}),('/entities/entity-1/profile','profile',{'entity_id':'entity-1'}),
    ('/relationships/timeline?entity_id=entity-1','timeline',{'entity_id':'entity-1'}),('/chapters/4','dossier',{'chapter_number':4}),('/entities/entity-1','article',{'entity_id':'entity-1'})])
def test_all_guide_reads_exact_verified_scoped_transport(client,db,test_user,test_library,auth_headers,path,operation,args):
    novel,chapters,run,point=owned_scope(db,test_user,test_library)
    upstream=AsyncMock(return_value={'items':[]})
    separator='&' if '?' in path else '?'
    with patch('app.routers.discovery.metadata_client.reader_story_guide',upstream):
        response=client.get(f'/discovery/novels/701/story-guide{path}{separator}through_chapter=999',headers=auth_headers)
    assert response.status_code==200,response.text
    assert response.headers['cache-control']=='private, no-store'
    expected={'through_chapter':5,'chapters':[{'chapter_number':chapter.chapter_number,'text_sha256':hashlib.sha256(' '.join(chapter.content.split()).encode()).hexdigest()} for chapter in chapters]}
    upstream.assert_awaited_once_with(701,operation=operation,scope=expected,args=args)
    if operation=='projection':assert response.json()['reader_context']=={'library_id':test_library.id,'novel_id':novel.id}


def test_unowned_and_no_progress_are_local_empty_without_upstream(client,db,test_user,test_library,auth_headers):
    db.add(Novel(title='No reads',metadata_id=702,library_id=test_library.id));db.commit()
    upstream=AsyncMock()
    with patch('app.routers.discovery.metadata_client.reader_story_guide',upstream):
        for metadata_id in (702,999999):
            for path in ('','/projection','/entities','/entities/future','/entities/future/profile','/relationships/timeline','/chapters/-1','/changes'):
                response=client.get(f'/discovery/novels/{metadata_id}/story-guide{path}?through_chapter=0',headers=auth_headers)
                assert response.status_code==200,response.text
                assert response.json()['safe_through_chapter'] is None
            for action in ('backfill','regenerate'):
                assert client.post(f'/discovery/novels/{metadata_id}/story-guide/{action}',headers=auth_headers).status_code==403
            assert client.post(f'/discovery/novels/{metadata_id}/story-guide/characters/portrait',headers=auth_headers,json={'name':'Future identity'}).status_code==403
        assert client.get('/discovery/story-guide/media/future?novel_id=999999',headers=auth_headers).status_code==403
        assert client.get('/discovery/story-guide/media/future',headers=auth_headers).status_code==422
    upstream.assert_not_awaited()


@pytest.mark.parametrize('requested,expected', [(-4,None),(-3,-3),(-2,-3),(-1,-1),(0,0),(99,3)])
def test_negative_zero_and_gapped_prefix_preserve_signed_cutoff(client,db,test_user,test_library,auth_headers,requested,expected):
    owned_scope(db,test_user,test_library,numbers=(-3,-1,0,3))
    upstream=AsyncMock(return_value={'safe_through_chapter':expected})
    with patch('app.routers.discovery.metadata_client.reader_story_guide',upstream):
        response=client.get(f'/discovery/novels/701/story-guide?through_chapter={requested}',headers=auth_headers)
    assert response.status_code==200,response.text
    if expected is None:
        upstream.assert_not_awaited();assert response.json()['through_chapter'] is None
    else:
        proof=upstream.await_args.kwargs['scope']
        assert proof['through_chapter']==expected and all(row['chapter_number']<=expected for row in proof['chapters'])


def test_unfinished_current_not_authorized_by_lifetime_receipt(client,db,test_user,test_library,auth_headers):
    owned_scope(db,test_user,test_library,numbers=(3,7,11),percent=37)
    upstream=AsyncMock(return_value={})
    with patch('app.routers.discovery.metadata_client.reader_story_guide',upstream):
        response=client.get('/discovery/novels/701/story-guide?through_chapter=999',headers=auth_headers)
    assert response.status_code==200
    assert upstream.await_args.kwargs['scope']['through_chapter']==7
    assert [row['chapter_number'] for row in upstream.await_args.kwargs['scope']['chapters']]==[3,7]


@pytest.mark.parametrize('mutation',['missing_checkpoint','revised_receipt','requires_review','changed_plain','missing_content'])
def test_first_unverified_chapter_stops_prefix_without_fetching_future_bodies(client,db,test_user,test_library,auth_headers,mutation):
    novel,chapters,run,point=owned_scope(db,test_user,test_library,numbers=(-3,0,7))
    middle=chapters[1]
    if mutation=='missing_checkpoint':db.query(ReadingHistory).filter_by(reading_run_key=run.run_key,chapter_number=0).delete()
    elif mutation=='revised_receipt':middle.document=from_text('Revised unknown text');middle.content=middle.document['plain_text']
    elif mutation=='requires_review':db.query(ChapterReadReceipt).filter_by(chapter_id=middle.id).one().requires_review=True
    elif mutation=='changed_plain':middle.content='Changed plaintext against stale rich version'
    else:middle.content_status=ContentStatus.MISSING
    db.commit()
    upstream=AsyncMock(return_value={})
    with patch('app.routers.discovery.metadata_client.reader_story_guide',upstream):
        response=client.get('/discovery/novels/701/story-guide',headers=auth_headers)
    assert response.status_code==200,response.text
    assert upstream.await_args.kwargs['scope']['through_chapter']==-3
    assert len(upstream.await_args.kwargs['scope']['chapters'])==1


@pytest.mark.parametrize('deleted_progress',[False,True])
def test_reread_unread_zero_fences_old_negative_zero_future_receipts(client,db,test_user,test_library,auth_headers,deleted_progress):
    from app.services.reading_run_service import action
    from app.schemas.reading_runs import ReadingRunAction
    novel,chapters,run,point=owned_scope(db,test_user,test_library,numbers=(-3,0,7))
    action(db,test_user.id,novel.id,ReadingRunAction(expected_revision=9,operation_id='safe-reread',reading_run_key=run.run_key),'start')
    if deleted_progress:
        db.delete(db.query(ReadingProgress).filter_by(novel_id=novel.id).one());db.commit()
    upstream=AsyncMock()
    with patch('app.routers.discovery.metadata_client.reader_story_guide',upstream):
        response=client.get('/discovery/novels/701/story-guide/projection?through_chapter=0',headers=auth_headers)
    assert response.status_code==200 and response.json()['safe_through_chapter'] is None
    upstream.assert_not_awaited()


@pytest.mark.parametrize('action,operation,payload,args', [('backfill','backfill',None,{})])
def test_explicit_actions_use_same_verified_scope(client,db,test_user,test_library,auth_headers,action,operation,payload,args):
    owned_scope(db,test_user,test_library)
    upstream=AsyncMock(return_value={'status':'queued'})
    with patch('app.routers.discovery.metadata_client.reader_story_guide',upstream):
        response=client.post(f'/discovery/novels/701/story-guide/{action}',headers=auth_headers,json=payload)
    assert response.status_code==200,response.text
    assert upstream.await_args.kwargs['operation']==operation and upstream.await_args.kwargs['args']==args
    assert upstream.await_args.kwargs['scope']['through_chapter']==5


def test_media_is_scoped_private_and_never_uses_legacy_artifact_proxy(client,db,test_user,test_library,auth_headers):
    owned_scope(db,test_user,test_library)
    upstream=AsyncMock(return_value=(b'fixture-webp','image/webp'))
    with patch('app.routers.discovery.metadata_client.reader_story_guide',upstream):
        response=client.get('/discovery/story-guide/media/verified?novel_id=701',headers=auth_headers)
    assert response.status_code==200 and response.content==b'fixture-webp'
    assert response.headers['cache-control']=='private, no-store'
    assert upstream.await_args.kwargs['operation']=='media' and upstream.await_args.kwargs['args']=={'artifact_id':'verified'}


@pytest.mark.parametrize('limit_name,value', [('MAX_CHAPTERS',2),('MAX_TEXT_BYTES',10),('MAX_CHAPTER_BYTES',10)])
def test_proof_limits_fail_explicitly_not_silent_truncation(client,db,test_user,test_library,auth_headers,monkeypatch,limit_name,value):
    from app.services import reader_story_scope_service
    owned_scope(db,test_user,test_library)
    monkeypatch.setattr(reader_story_scope_service,limit_name,value)
    upstream=AsyncMock()
    with patch('app.routers.discovery.metadata_client.reader_story_guide',upstream):
        response=client.get('/discovery/novels/701/story-guide',headers=auth_headers)
    assert response.status_code==422
    upstream.assert_not_awaited()


def test_populated_foreign_copy_never_authorizes_sharedguide(client,db,test_user,test_library,auth_headers):
    from app.models import User,Library
    foreign=User(username='foreign-guide-owner',password='unused');db.add(foreign);db.flush()
    library=Library(user_id=foreign.id,name='Foreign');db.add(library);db.flush()
    owned_scope(db,foreign,library)
    upstream=AsyncMock()
    with patch('app.routers.discovery.metadata_client.reader_story_guide',upstream):
        response=client.get('/discovery/novels/701/story-guide',headers=auth_headers)
    assert response.status_code==200 and response.json()['through_chapter'] is None
    upstream.assert_not_awaited()


def test_unverified_middle_stops_before_later_private_body_load(client,db,test_user,test_library,auth_headers):
    from sqlalchemy import event
    novel,chapters,run,point=owned_scope(db,test_user,test_library,numbers=(-3,0,7))
    db.query(ChapterReadReceipt).filter_by(chapter_id=chapters[1].id).delete();db.commit()
    bodies=[]
    def observe(conn,cursor,statement,params,context,many):
        if 'chapters.content AS chapters_content' in statement and 'WHERE chapters.id =' in statement:bodies.append(params)
    event.listen(db.bind,'before_cursor_execute',observe)
    try:
        with patch('app.routers.discovery.metadata_client.reader_story_guide',AsyncMock(return_value={})):
            response=client.get('/discovery/novels/701/story-guide',headers=auth_headers)
    finally:event.remove(db.bind,'before_cursor_execute',observe)
    assert response.status_code==200 and len(bodies)==2
    # One verified body before upstream, the same body again after network
    # revalidation; no unread middle/future chapter is loaded.
    assert bodies[0]==bodies[1]
    assert bodies[0][-2]==chapters[0].id


def test_scoped_metadata_client_preserves_proof_and_sanitizes_failure():
    import asyncio
    import httpx
    from fastapi import HTTPException
    from app.services import metadata_client
    proof={'through_chapter':-3,'chapters':[{'chapter_number':-3,'text_sha256':'a'*64}]}
    request=httpx.Request('POST','http://fixture.invalid/reader')
    response=httpx.Response(200,json={'safe_through_chapter':-3},request=request)
    upstream=AsyncMock(return_value=response)
    with patch.object(metadata_client,'_request',upstream):
        result=asyncio.run(metadata_client.reader_story_guide(77,operation='guide',scope=proof,args={}))
    assert result=={'safe_through_chapter':-3}
    assert upstream.await_args.args==('POST','/analysis/novels/77/story-guide/reader')
    assert upstream.await_args.kwargs['json']=={'operation':'guide','scope':proof,'args':{}}
    status=httpx.HTTPStatusError('PRIVATE FUTURE ERROR',request=request,response=httpx.Response(409,json={'detail':'PRIVATE FUTURE TEXT'},request=request))
    failure=RuntimeError('PRIVATE FUTURE ERROR');failure.__cause__=status
    with patch.object(metadata_client,'_request',AsyncMock(side_effect=failure)):
        with pytest.raises(HTTPException) as blocked:asyncio.run(metadata_client.reader_story_guide(77,operation='guide',scope=proof))
    assert blocked.value.status_code==409 and 'PRIVATE' not in str(blocked.value.detail)


def test_postgresql_current_receipt_json_join_and_signed_verified_prefix():
    import os
    from sqlalchemy import create_engine,text
    from sqlalchemy.orm import sessionmaker
    from config.database import Base
    from app.models import User,Library
    from app.services.reader_story_scope_service import scope
    url=os.environ.get('NEXUS_TEST_POSTGRES_URL')
    if not url:pytest.skip('Requires owned disposable PostgreSQL')
    schema='guide_scope_'+uuid4().hex
    admin=create_engine(url);engine=None
    try:
        with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as db:
            user=User(username='guide-owner',password='unused');db.add(user);db.flush()
            library=Library(user_id=user.id,name='Proof fixture');db.add(library);db.flush()
            novel,chapters,run,point=owned_scope(db,user,library,numbers=(-3,0,7))
            proof,_=scope(db,user.id,701)
            assert proof['through_chapter']==7 and [row['chapter_number'] for row in proof['chapters']]==[-3,0,7]
            db.query(ReadingHistory).filter_by(user_id=user.id,novel_id=novel.id,reading_run_key=run.run_key,chapter_number=0).delete();db.commit()
            proof,_=scope(db,user.id,701)
            assert proof['through_chapter']==-3 and len(proof['chapters'])==1
    finally:
        if engine is not None:engine.dispose()
        with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA IF EXISTS {schema} CASCADE'))
        admin.dispose()


def test_provenanced_portrait_urls_only_use_authenticated_scoped_media_proxy(client,db,test_user,test_library,auth_headers):
    owned_scope(db,test_user,test_library)
    upstream=AsyncMock(return_value={'characters':[{'name':'Read person','portrait':{'id':'verified-artifact','url':'/v1/media/verified-artifact','label':'Allowed'}},
        {'name':'Missing provenance','portrait':{'url':'https://elsewhere.invalid/unscoped'}}]})
    with patch('app.routers.discovery.metadata_client.reader_story_guide',upstream):
        response=client.get('/discovery/novels/701/story-guide',headers=auth_headers)
    assert response.status_code==200,response.text
    characters=response.json()['characters']
    assert characters[0]['portrait']['url']=='/discovery/story-guide/media/verified-artifact?novel_id=701'
    assert 'portrait' not in characters[1]


@pytest.mark.parametrize('ao3',[False,True])
@pytest.mark.parametrize('action',['regenerate','characters/portrait'])
def test_reader_mutations_cannot_bypass_private_provider_permissions_budget_or_ao3(client,db,test_user,test_library,auth_headers,ao3,action):
    from app.models import ReaderProvider,StoryProcessingPermission,ReaderProviderRequest
    novel,chapters,run,point=owned_scope(db,test_user,test_library)
    if ao3:
        novel.novel_site='archive';novel.source_url='https://archiveofourown.org/works/123'
    provider=ReaderProvider(user_id=test_user.id,name='Private paid provider',kind='openai_compatible',base_url='https://provider.invalid/v1',model='fixture-model',
        budget_microusd=1000000,used_microusd=0,reserved_microusd=0)
    db.add(provider);db.flush()
    db.add(StoryProcessingPermission(user_id=test_user.id,novel_id=novel.id,provider_id=provider.id,companion=True,translation=False,ao3_consent=ao3))
    db.commit()
    upstream=AsyncMock(return_value={'status':'queued','id':'must-not-queue'})
    with patch('app.routers.discovery.metadata_client.reader_story_guide',upstream):
        response=client.post(f'/discovery/novels/701/story-guide/{action}?provider_id={provider.id}',headers=auth_headers,
            json={'name':'Read person','description':'Verified read evidence','provider_id':provider.id} if action=='characters/portrait' else None)
    assert response.status_code==403,response.text
    assert response.json()['detail']['code']=='reader_provider_required'
    assert 'private provider' in response.json()['detail']['message']
    upstream.assert_not_awaited()
    assert not db.query(ReaderProviderRequest).count()
    db.refresh(provider)
    assert provider.used_microusd==provider.reserved_microusd==0


def test_guide_discards_old_reading_after_reread_during_upstream(client,db,test_user,test_library,auth_headers):
    from app.services.reading_run_service import action
    from app.schemas.reading_runs import ReadingRunAction
    novel,_,run,point=owned_scope(db,test_user,test_library)
    novel_id=novel.id;user_id=test_user.id;run_key=run.run_key
    async def upstream(*args,**kwargs):
        action(db,user_id,novel_id,ReadingRunAction(expected_revision=9,operation_id='during-guide-rpc',reading_run_key=run_key),'start')
        return {'characters':[{'name':'OLD READING SECRET'}]}
    with patch('app.routers.discovery.metadata_client.reader_story_guide',upstream):
        response=client.get('/discovery/novels/701/story-guide',headers=auth_headers)
    assert response.status_code==409,response.text
    assert response.json()['detail']['code']=='reading_scope_changed'
    assert 'OLD READING SECRET' not in response.text
