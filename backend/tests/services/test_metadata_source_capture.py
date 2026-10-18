"""Exhaustive source membership is distinct from a cached database listing."""
import asyncio
import copy
import hashlib
import json
from uuid import uuid4

import httpx
import pytest

from app.services import metadata_client as client
from tests.services.test_metadata_chapter_manifest import row, SOURCE, KEY, CAPABILITIES, pages

CAPTURE = str(uuid4())
REVIEW = str(uuid4())
CAPS = {**CAPABILITIES, 'source_manifest_protocols': [1]}


def capture(rows, size=1000, authority='adapter_stable'):
    fingerprint = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    summary = dict(id=CAPTURE, captured_at='2026-10-16T20:00:00Z', fingerprint=fingerprint,
        total=len(rows), source_complete=True, deletion_authoritative=authority!='raw_observation',
        authority_kind=authority, review_id=REVIEW if authority=='reviewed_mapping' else None)
    head = dict(protocol=1, novel_id=123, manifest_key=KEY, revision='a'*64, source=copy.deepcopy(SOURCE), capture=summary)
    body = {key: head[key] for key in ('protocol','novel_id','manifest_key','revision','source')}
    body.update({key: value for key,value in summary.items() if key not in {'id','captured_at'}})
    body.update(capture_id=CAPTURE, complete=True)
    batches = [dict(body, items=copy.deepcopy(rows[start:start+size]), has_more=start+size<len(rows),
        next_cursor=str(start+size) if start+size<len(rows) else None)
        for start in range(0,len(rows),size)] or [dict(body, items=[], has_more=False, next_cursor=None)]
    return copy.deepcopy(head), batches


def transport(monkeypatch, head, batches, *, final=None, capability=None, lineage_damage=None):
    calls=[]; remaining=iter(copy.deepcopy(batches)); heads=iter([copy.deepcopy(head), copy.deepcopy(head if final is None else final)])
    observed=[item for page in batches for item in page.get('items',[])]
    lineage=[dict(capture_ordinal=i,old_chapter_key=str(uuid4()),new_chapter_key=item['chapter_key']) for i,item in enumerate(observed)]
    lineage_hash=hashlib.sha256(json.dumps(lineage,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    async def request(method,path,**kwargs):
        calls.append((path,kwargs.get('params')))
        if path.endswith('manifest-capabilities'):
            value=CAPS if capability is None else capability
        elif path.endswith('source-manifest-head'):
            value=next(heads)
        elif path.endswith('/lineage'):
            offset=kwargs['params']['offset'];limit=kwargs['params']['limit'];summary=head['capture']
            value={key:head[key] for key in ('protocol','novel_id','manifest_key','revision','source')}
            value.update(capture_id=summary['id'],fingerprint=summary['fingerprint'],review_id=summary['review_id'],
                lineage_fingerprint=lineage_hash,total=summary['total'],offset=offset,limit=limit,
                has_more=offset+limit<len(lineage),next_offset=offset+limit if offset+limit<len(lineage) else None,
                items=copy.deepcopy(lineage[offset:offset+limit]))
            if lineage_damage:lineage_damage(value)
        else:
            value=next(remaining)
        if isinstance(value,BaseException):raise value
        return httpx.Response(200,json=value)
    monkeypatch.setattr(client,'_request',request)
    client.clear_cache()
    return calls


def test_complete_source_capture_exhausts_pages_and_preserves_audited_authority(monkeypatch):
    rows=[row(i,-100000+i*3) for i in range(1,2006)]
    head,batches=capture(rows)
    calls=transport(monkeypatch,head,batches)
    result=asyncio.run(client.get_chapter_manifest(123))
    assert result.items==rows and result.source_complete and result.deletion_authoritative
    assert result.source_capture_id==CAPTURE and result.source_authority_kind=='adapter_stable'
    assert result.source_review_id is None and len(calls)==6
    assert calls[3][1]['cursor']=='1000' and calls[3][1]['revision']==head['revision']
    assert not any(path.endswith('/manifest') for path,_ in calls)
    assert not client.cache._cache


def test_explicit_reviewed_positional_mapping_is_accepted_without_claiming_stable_source_ids(monkeypatch):
    rows=[dict(row(1),identity_kind='positional')]
    head,batches=capture(rows,authority='reviewed_mapping')
    transport(monkeypatch,head,batches)
    result=asyncio.run(client.get_chapter_manifest(123))
    assert result.identity_kind=='positional' and result.source_review_id==REVIEW
    assert result.deletion_authoritative
    assert result.source_lineage[0]['new_chapter_key']==rows[0]['chapter_key']
    assert result.source_lineage_fingerprint


def test_raw_positional_capture_requires_review_and_never_uses_old_database_rows(monkeypatch):
    head,batches=capture([dict(row(1),id=None,chapter_key=None,identity_kind='positional')],authority='raw_observation')
    calls=transport(monkeypatch,head,batches)
    with pytest.raises(client.ChapterManifestError) as caught:asyncio.run(client.get_chapter_manifest(123))
    assert caught.value.category=='source_review_required' and len(calls)==2


def test_peer_without_source_observation_retains_non_authoritative_database_compatibility(monkeypatch):
    head,_=capture([]);head['capture']=None
    calls=transport(monkeypatch,head,pages([row(1)]))
    result=asyncio.run(client.get_chapter_manifest(123))
    assert result.items==[row(1)] and not result.source_complete and not result.deletion_authoritative
    assert result.source_capture_id is None and len(calls)==3


@pytest.mark.parametrize('authority',['adapter_stable','reviewed_mapping'])
def test_empty_accepted_source_is_exhaustively_hashed_and_rechecked(monkeypatch,authority):
    head,batches=capture([],authority=authority)
    calls=transport(monkeypatch,head,batches)
    result=asyncio.run(client.get_chapter_manifest(123))
    assert result.total==0 and result.items==[] and len(calls)==(5 if authority=='reviewed_mapping' else 4)


@pytest.mark.parametrize('damage',['truncated','empty_middle','cycle','digest','duplicate_id','duplicate_key',
    'duplicate_number','duplicate_source_id','out_of_order','foreign_site','foreign_story','body','null_key',
    'positional','false_complete','bool_more','extra_page','changed_capture','changed_source','changed_review',
    'changed_authority','changed_count','changed_revision','bool_source'])
def test_malformed_changed_or_incomplete_capture_never_falls_back(monkeypatch,damage):
    head,batches=capture([row(1),row(2),row(3)],size=1)
    if damage=='truncated':batches[-1]['items']=[]
    elif damage=='empty_middle':batches[1]['items']=[]
    elif damage=='cycle':batches[1]['next_cursor']=batches[0]['next_cursor']
    elif damage=='digest':batches[-1]['items'][0]['title']='Silent modification'
    elif damage=='duplicate_id':batches[1]['items'][0]['id']=1
    elif damage=='duplicate_key':batches[1]['items'][0]['chapter_key']=batches[0]['items'][0]['chapter_key'].replace('-','')
    elif damage=='duplicate_number':batches[1]['items'][0]['chapter_number']=1
    elif damage=='duplicate_source_id':batches[1]['items'][0]['chapter_id']=batches[0]['items'][0]['chapter_id']
    elif damage=='out_of_order':batches[1]['items'][0]['chapter_number']=-4
    elif damage=='foreign_site':batches[1]['items'][0]['site']='archive'
    elif damage=='foreign_story':batches[1]['items'][0]['story_id']=999
    elif damage=='body':batches[1]['items'][0]['text']='Must not be in catalog descriptor'
    elif damage=='null_key':batches[1]['items'][0]['chapter_key']=None
    elif damage=='positional':batches[1]['items'][0]['identity_kind']='positional'
    elif damage=='false_complete':batches[1]['complete']=False
    elif damage=='bool_more':batches[1]['has_more']=1
    elif damage=='extra_page':batches[1]['unexpected']='field'
    elif damage=='changed_capture':batches[1]['capture_id']=str(uuid4())
    elif damage=='changed_source':batches[1]['source']={**SOURCE,'source_url':'https://other.invalid'}
    elif damage=='changed_review':batches[1]['review_id']=REVIEW
    elif damage=='changed_authority':batches[1]['deletion_authoritative']=False
    elif damage=='changed_count':batches[1]['total']=4
    elif damage=='changed_revision':batches[1]['revision']='b'*64
    elif damage=='bool_source':batches[1]['source']={**SOURCE,'story_id':True}
    transport(monkeypatch,head,batches)
    with pytest.raises(client.ChapterManifestError):asyncio.run(client.get_chapter_manifest(123,page_size=1))
    assert not client.cache._cache


@pytest.mark.parametrize('damage',['source','revision','capture','none','manifest'])
def test_final_head_recheck_discards_late_replacements(monkeypatch,damage):
    head,batches=capture([row(1)])
    final=copy.deepcopy(head)
    if damage=='source':final['source']['source_url']='https://other.invalid'
    elif damage=='revision':final['revision']='c'*64
    elif damage=='capture':final['capture']['id']=str(uuid4())
    elif damage=='none':final['capture']=None
    else:final['manifest_key']=str(uuid4())
    transport(monkeypatch,head,batches,final=final)
    with pytest.raises(client.ChapterManifestError) as caught:asyncio.run(client.get_chapter_manifest(123))
    assert caught.value.category=='manifest_changed' and caught.value.retryable


@pytest.mark.parametrize('damage',['bool_protocol','wrong_work','bad_source','missing_summary','invalid_date','invalid_kind',
    'unreviewed_id','missing_review_id','incomplete','no_authority','extra_header','capacity'])
def test_untrusted_head_never_becomes_authoritative(monkeypatch,damage):
    head,batches=capture([row(1)])
    if damage=='bool_protocol':head['protocol']=True
    elif damage=='wrong_work':head['novel_id']=555
    elif damage=='bad_source':head['source']['story_id']=False
    elif damage=='missing_summary':del head['capture']['id']
    elif damage=='invalid_date':head['capture']['captured_at']='yesterday'
    elif damage=='invalid_kind':head['capture']['authority_kind']=[]
    elif damage=='unreviewed_id':head['capture']['review_id']=REVIEW
    elif damage=='missing_review_id':head['capture']['authority_kind']='reviewed_mapping'
    elif damage=='incomplete':head['capture']['source_complete']=False
    elif damage=='no_authority':head['capture']['deletion_authoritative']=False
    elif damage=='extra_header':head['other']='field'
    elif damage=='capacity':head['capture']['total']=client.MAX_MANIFEST_ITEMS+1
    transport(monkeypatch,head,batches)
    with pytest.raises(client.ChapterManifestError):asyncio.run(client.get_chapter_manifest(123))


def test_byte_limit_is_actionable_without_partial_saved_rows(monkeypatch):
    head,batches=capture([row(1)])
    transport(monkeypatch,head,batches)
    monkeypatch.setattr(client,'MAX_MANIFEST_BYTES',2)
    with pytest.raises(client.ChapterManifestError) as caught:asyncio.run(client.get_chapter_manifest(123))
    assert caught.value.category=='manifest_limit'


def test_actual_capture_service_and_dto_wire_never_selects_story_bodies(tmp_path,monkeypatch):
    from pathlib import Path
    from datetime import datetime
    metadata_src=Path(__file__).resolve().parents[4]/'nexus-server'/'src'
    monkeypatch.syspath_prepend(str(metadata_src))
    pytest.importorskip('aiosqlite')
    pytest.importorskip('greenlet')
    from fastapi import FastAPI
    from sqlalchemy import event,update
    from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
    import nexus.database.models  # noqa:F401
    from nexus.database.base import Base
    from nexus.database.models.novel import Novel,Chapter
    from nexus.database.models.source_manifest import SourceManifestCapture,SourceManifestItem
    from nexus.services import chapter_manifest,source_manifest_capture
    from nexus.api.routers.source_manifests import router
    from nexus.api.deps import get_db
    from nexus.api.auth import verify_api_key
    from nexus.schemas.chapter_manifest import ManifestCapabilities
    async def qualify():
        engine=create_async_engine(f'sqlite+aiosqlite:///{tmp_path/"source-wire.db"}')
        try:
            async with engine.begin() as connection:await connection.run_sync(Base.metadata.create_all)
            sessions=async_sessionmaker(engine,expire_on_commit=False)
            async with sessions() as db:
                db.add(Novel(id=123,title='Permitted fixture',novel_site='royalroad',story_id=123,
                    source_url=SOURCE['source_url'],created_at=datetime.now(),updated_at=datetime.now()))
                await db.flush()
                for n in range(1,4):
                    db.add(Chapter(novel_fk=123,site='royalroad',story_id=123,chapter_id=100+n,
                        chapter_number=n*7,title=f'Fixture {n}',text='Must not select this body',rich_html='<p>Private body</p>',
                        created_at=datetime.now(),updated_at=datetime.now()))
                await db.commit()
                initial=await chapter_manifest.page(db,123)
                # Persist through the real immutable models; parser completeness
                # has separate native tests. Here qualify actual RPC serialization,
                # signed cursor, namespace/revision checks and Novel consumption.
                cap=SourceManifestCapture(id=CAPTURE,sequence=1,novel_id=123,
                    manifest_key=initial['manifest_key'],manifest_revision=initial['revision'],source=SOURCE,
                    binding=hashlib.sha256(chapter_manifest.canonical(SOURCE)).hexdigest(),proof={},
                    authority_kind='adapter_stable',review_id=None,total=3,source_complete=True,deletion_authoritative=True,
                    fingerprint=hashlib.sha256(chapter_manifest.canonical(initial['items'])).hexdigest())
                db.add(cap);await db.flush()
                db.add_all([SourceManifestItem(capture_id=CAPTURE,ordinal=i,chapter_key=item['chapter_key'],item=item)
                    for i,item in enumerate(initial['items'])]);await db.commit()
            statements=[]
            @event.listens_for(engine.sync_engine,'before_cursor_execute')
            def sql(_c,_u,statement,_p,_ctx,_m):statements.append(statement)
            app=FastAPI()
            async def database():
                async with sessions() as db:yield db
            app.include_router(router,prefix='/chapters')
            from nexus.api.routers.source_manifest_review import reader_router
            app.include_router(reader_router)
            app.dependency_overrides[get_db]=database
            app.dependency_overrides[verify_api_key]=lambda:None
            @app.get('/chapters/manifest-capabilities',response_model=ManifestCapabilities)
            async def capabilities():return chapter_manifest.capabilities()
            calls=[];mutate=False
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://source.test') as upstream:
                async def request(method,path,**kwargs):
                    nonlocal mutate
                    response=await upstream.request(method,path,params=kwargs.get('params'))
                    calls.append(path);response.raise_for_status()
                    if mutate and '/source-manifest-captures/' in path:
                        mutate=False
                        async with sessions() as db:
                            await db.execute(update(Novel).where(Novel.id==123).values(source_url='https://changed.invalid/123'))
                            await db.commit()
                    return response
                monkeypatch.setattr(client,'_request',request)
                result=await client.get_chapter_manifest(123,page_size=1)
                assert result.items==initial['items'] and result.source_capture_id==CAPTURE
                assert result.source_complete and result.deletion_authoritative and len(calls)==6
                assert not any('chapters.text' in statement or 'chapters.rich_html' in statement for statement in statements)
                # Exercise real administrator preview/apply and the ordinary
                # service-key lineage projection through the Novel client.
                # Native FFN parsing/completeness is tested independently.
                from nexus.services import source_manifest_review as review_service
                from nexus.schemas.source_manifest_review import SourceManifestReviewPreviewInput,SourceManifestReviewAction
                source=dict(site='fanfiction',story_id=456,source_url='https://www.fanfiction.net/s/456/1/Fixture')
                async with sessions() as db:
                    db.add(Novel(id=456,title='Permitted positional fixture',novel_site='fanfiction',story_id=456,
                        source_url=source['source_url'],created_at=datetime.now(),updated_at=datetime.now()))
                    await db.flush()
                    db.add(Chapter(novel_fk=456,site='fanfiction',story_id=456,chapter_id=1,chapter_number=1,
                        title='The original letter',text='Original retained body',created_at=datetime.now(),updated_at=datetime.now()))
                    await db.commit()
                    initial_positional=await chapter_manifest.page(db,456)
                    raw_items=[dict(initial_positional['items'][0],id=None,chapter_key=None)]
                    raw=SourceManifestCapture(id=str(uuid4()),sequence=1,novel_id=456,
                        manifest_key=initial_positional['manifest_key'],manifest_revision=initial_positional['revision'],source=source,
                        binding=hashlib.sha256(chapter_manifest.canonical(source)).hexdigest(),proof={},
                        authority_kind='raw_observation',review_id=None,total=1,source_complete=True,deletion_authoritative=False,
                        fingerprint=hashlib.sha256(chapter_manifest.canonical(raw_items)).hexdigest())
                    db.add(raw);await db.flush()
                    db.add(SourceManifestItem(capture_id=raw.id,ordinal=0,chapter_key=None,item=raw_items[0]));await db.commit()
                    actor=str(uuid4())
                    preview=await review_service.preview(db,SourceManifestReviewPreviewInput(actor_id=actor,novel_id=456,
                        capture_id=raw.id,expected_manifest_key=initial_positional['manifest_key'],expected_revision=initial_positional['revision'],
                        mappings=[dict(capture_ordinal=0,chapter_key=initial_positional['items'][0]['chapter_key'],new_lifecycle=False)]))
                    assert preview['ready']
                    applied=await review_service.decide(db,preview['id'],SourceManifestReviewAction(actor_id=actor,
                        expected_revision=preview['revision'],operation_id=str(uuid4()),review_token=preview['review_token']),'apply')
                    assert applied['review']['status']=='applied'
                reviewed=await client.get_chapter_manifest(456,page_size=1)
                assert reviewed.source_authority_kind=='reviewed_mapping' and reviewed.source_review_id==preview['id']
                assert reviewed.identity_kind=='positional' and reviewed.items[0]['chapter_key']!=initial_positional['items'][0]['chapter_key']
                assert reviewed.source_lineage==[dict(capture_ordinal=0,old_chapter_key=initial_positional['items'][0]['chapter_key'],
                    new_chapter_key=reviewed.items[0]['chapter_key'])]
                # The actual metadata service rejects the next page after a
                # concurrent namespace change; no legacy route is consulted.
                mutate=True
                with pytest.raises(client.ChapterManifestError) as caught:await client.get_chapter_manifest(123,page_size=1)
                assert caught.value.category=='manifest_changed' and caught.value.retryable
                assert not any(path.endswith('/manifest') for path in calls)
                async with sessions() as db:
                    observed=await source_manifest_capture.head(db,123)
                    assert observed['capture'] is None
        finally:
            await engine.dispose();client.clear_cache()
    asyncio.run(qualify())


def test_removed_capture_is_retryable_change_not_permission_to_use_old_database_listing(monkeypatch):
    head,batches=capture([row(1)])
    calls=[]
    async def request(method,path,**kwargs):
        calls.append(path)
        if path.endswith('manifest-capabilities'):return httpx.Response(200,json=CAPS)
        if path.endswith('source-manifest-head'):return httpx.Response(200,json=head)
        raise httpx.HTTPStatusError('synthetic missing capture',request=httpx.Request('GET','http://fixture.invalid'),
            response=httpx.Response(404,json={'detail':{'code':'capture_not_found'}}))
    monkeypatch.setattr(client,'_request',request)
    with pytest.raises(client.ChapterManifestError) as caught:asyncio.run(client.get_chapter_manifest(123))
    assert caught.value.category=='manifest_changed' and caught.value.retryable
    assert len(calls)==3 and not any(path.endswith('/manifest') for path in calls)


@pytest.mark.parametrize('damage',['foreign_capture','foreign_work','foreign_manifest','foreign_review','foreign_source',
    'foreign_new_key','invalid_old_key','wrong_ordinal','truncated','digest','extra_text','bool_offset','bad_next','extra_page'])
def test_reviewed_lineage_is_bounded_complete_and_tied_to_exact_new_chapters(monkeypatch,damage):
    rows=[dict(row(i),identity_kind='positional') for i in (1,2)]
    head,batches=capture(rows,size=1,authority='reviewed_mapping')
    def mutate(page):
        if damage=='foreign_capture':page['capture_id']=str(uuid4())
        elif damage=='foreign_work':page['novel_id']=999
        elif damage=='foreign_manifest':page['manifest_key']=str(uuid4())
        elif damage=='foreign_review':page['review_id']=str(uuid4())
        elif damage=='foreign_source':page['source']={**SOURCE,'source_url':'https://other.invalid'}
        elif damage=='foreign_new_key':page['items'][0]['new_chapter_key']=str(uuid4())
        elif damage=='invalid_old_key':page['items'][0]['old_chapter_key']='chapter1'
        elif damage=='wrong_ordinal':page['items'][0]['capture_ordinal']=True
        elif damage=='truncated':page['items']=[]
        elif damage=='digest':page['lineage_fingerprint']='0'*64
        elif damage=='extra_text':page['items'][0]['text']='Must not belong here'
        elif damage=='bool_offset':page['offset']=False
        elif damage=='bad_next':page['next_offset']=0
        elif damage=='extra_page':page['extra']='unexpected'
    calls=transport(monkeypatch,head,batches,lineage_damage=mutate)
    with pytest.raises(client.ChapterManifestError):asyncio.run(client.get_chapter_manifest(123,page_size=1))
    assert not any(path.endswith('/manifest') for path,_ in calls)


def test_reviewed_lineage_is_exhaustive_across_pages_and_mutable_results_do_not_escape_a_cache(monkeypatch):
    rows=[dict(row(i),identity_kind='positional') for i in range(1,1003)]
    head,batches=capture(rows,authority='reviewed_mapping')
    calls=transport(monkeypatch,head,batches)
    result=asyncio.run(client.get_chapter_manifest(123))
    assert len(result.source_lineage)==1002 and result.source_lineage[-1]['capture_ordinal']==1001
    assert len([path for path,_ in calls if path.endswith('/lineage')])==2
    assert not client.cache._cache
