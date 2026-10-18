"""Real database reviews never infer identity from labels or discard originals."""
# ruff: noqa: F811
import asyncio
import sys
from types import SimpleNamespace
from uuid import uuid4
import pytest
from fastapi import HTTPException
from app.models import Chapter
from app.models.chapter_manifest import ChapterManifestState
from app.schemas.chapter_manifest import ManifestPreviewInput,ManifestApplyInput,ManifestUndoInput,ManifestReviewView
from app.services import chapter_manifest_service as service
from app.services.metadata_client import ChapterManifestSnapshot
from app.services.chapter_document import from_text
from tests.routes.test_reader_tools import story
from tests.routes.conftest import db,test_user,test_library  # noqa: F401


@pytest.fixture
def case(db,test_library,monkeypatch):
    novel,first,second=story(db,test_library)
    novel.metadata_id=123;novel.site='royalroad';novel.novel_site='royalroad';novel.site_story_id=81
    for index,chapter in enumerate((first,second)):
        chapter.chapter_number=(-2,7)[index];chapter.site_chapter_id=100+index
        chapter.content=f'Untouched original {index}';chapter.document=from_text(chapter.content)
    db.commit()
    manifest_key=str(uuid4());remote_keys=[str(uuid4()),str(uuid4())]
    remote=ChapterManifestSnapshot(novel_id=123,manifest_key=manifest_key,revision='1'*64,fingerprint='2'*64,identity_kind='stable_source_id',total=2,
        source={'site':'royalroad','story_id':81,'source_url':'https://www.royalroad.com/fiction/81'},items=[
            dict(id=index+1,chapter_key=remote_keys[index],site='royalroad',story_id=81,chapter_id=100+index,chapter_number=(-10,30)[index],title='Same generic title',url=f'https://www.royalroad.com/fiction/81/chapter/{100+index}',category='story',word_count=10,identity_kind='stable_source_id') for index in range(2)])
    async def fetch(*args,**kwargs):return remote
    monkeypatch.setattr(service.metadata_client,'get_chapter_manifest',fetch)
    # This tests only the core transaction. Production requires the root-owned
    # complete ancillary guard; never publish a stub in application source.
    monkeypatch.setitem(sys.modules,'app.services.chapter_topology_guards',SimpleNamespace(TOPOLOGY_GUARDS_COMPLETE=True,require_complete_guards=lambda *_:None))
    return novel,first,second,remote


def preview(db,user,novel,**kwargs):
    state=db.get(ChapterManifestState,novel.id)
    value=ManifestPreviewInput(expected_manifest_epoch=state.manifest_epoch,expected_manifest_revision=str(state.revision),**kwargs)
    return asyncio.run(service.preview(db,user.id,novel.id,value))


def test_review_pages_signed_mapping_apply_undo_and_historical_ack(db,test_user,case):
    novel,first,second,remote=case
    original_keys=(first.chapter_key,second.chapter_key)
    original_bodies=(first.content,second.content)
    result=preview(db,test_user,novel)
    ManifestReviewView.model_validate(result)
    assert result['can_apply'] and result['counts']['renumbered']==2
    assert {row['decision'] for row in result['items']['items']}=={'stable_source_id'}
    assert service.review_page(db,test_user.id,novel.id)['items'][0]['review_id']==result['review_id']
    assert service.remote_choices(db,test_user.id,novel.id,result['review_id'],ids=[remote.items[1]['chapter_key']])['items'][0]['chapter_number']==30
    request=ManifestApplyInput(review_token=result['review_token'],operation_id='apply-exact')
    receipt=asyncio.run(service.apply(db,test_user.id,novel.id,request))
    db.expire_all();chapters=db.query(Chapter).filter_by(novel_id=novel.id).order_by(Chapter.chapter_number).all()
    assert [row.chapter_number for row in chapters]==[-10,30]
    assert tuple(row.chapter_key for row in chapters)==original_keys and tuple(row.content for row in chapters)==original_bodies
    assert asyncio.run(service.apply(db,test_user.id,novel.id,request))==receipt
    current=service.review_view(db,test_user.id,novel.id,result['review_id'])
    assert current['can_undo'] and current['manifest_revision']!=current['reviewed_manifest_revision']
    undo=ManifestUndoInput(expected_revision=current['revision'],expected_manifest_epoch=current['manifest_epoch'],expected_manifest_revision=current['manifest_revision'],operation_id='undo-exact')
    undone=service.undo(db,test_user.id,novel.id,result['review_id'],undo)
    assert undone['status']=='undone'
    assert asyncio.run(service.apply(db,test_user.id,novel.id,request))==receipt
    assert service.review_view(db,test_user.id,novel.id,result['review_id'])['status']=='undone'
    assert [row.chapter_number for row in db.query(Chapter).filter_by(novel_id=novel.id).order_by(Chapter.chapter_number)]==[-2,7]
    assert db.get(ChapterManifestState,novel.id).identity_required


def test_no_number_title_or_positional_identity_inference(db,test_user,case):
    novel,first,second,remote=case
    for item in remote.items:item['identity_kind']='positional'
    remote.items[0]['chapter_number']=-2;remote.items[1]['chapter_number']=7
    result=preview(db,test_user,novel)
    assert result['counts']['unmapped']==2 and not result['can_apply']
    assert 'unmapped_local_chapters' in {item['code'] for item in result['blocked_reasons']}
    assert len(result['unmapped']['items'])==2


def test_changed_original_blocks_apply_without_mutation(db,test_user,case):
    novel,first,_,_=case
    result=preview(db,test_user,novel)
    first.content='Revised original';db.commit()
    with pytest.raises(HTTPException) as caught:
        asyncio.run(service.apply(db,test_user.id,novel.id,ManifestApplyInput(review_token=result['review_token'],operation_id='stale')))
    assert caught.value.status_code==409 and caught.value.detail['code']=='review_stale'
    db.rollback();assert first.chapter_number==-2


def test_current_content_and_archived_original_use_exact_uuid(db,test_user,case):
    novel,first,_,_=case;key=first.chapter_key;body=first.content
    first.archived=True;db.commit()
    result=service.keyed_content(db,test_user.id,novel.id,key)
    assert result['archived'] and result['content']==body and result['source_version']==result['current_content_version']
    assert service.resolve_key(db,test_user.id,novel.id,key)['archived']


def test_preview_does_not_hold_transaction_across_remote_and_rechecks_revocation(db,test_user,case,monkeypatch):
    novel,first,_,remote=case
    async def revoke(*args,**kwargs):
        assert not db.in_transaction()
        test_user.is_disabled=True;db.commit()
        return remote
    monkeypatch.setattr(service.metadata_client,'get_chapter_manifest',revoke)
    with pytest.raises(HTTPException) as caught:preview(db,test_user,novel)
    assert caught.value.status_code==401
    db.rollback();assert first.chapter_number==-2


def test_source_revision_change_after_review_is_not_applied(db,test_user,case):
    novel,first,_,remote=case
    result=preview(db,test_user,novel)
    object.__setattr__(remote,'revision','3'*64)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(service.apply(db,test_user.id,novel.id,ManifestApplyInput(review_token=result['review_token'],operation_id='changed-source')))
    assert caught.value.detail['code']=='review_stale'
    db.rollback();assert first.chapter_number==-2


def test_undo_refuses_later_original_change(db,test_user,case):
    novel,first,_,_=case;result=preview(db,test_user,novel)
    receipt=asyncio.run(service.apply(db,test_user.id,novel.id,ManifestApplyInput(review_token=result['review_token'],operation_id='apply-before-edit')))
    first.content='Later private source text';db.commit()
    with pytest.raises(HTTPException) as caught:
        service.undo(db,test_user.id,novel.id,result['review_id'],ManifestUndoInput(expected_revision=receipt['revision'],expected_manifest_epoch=receipt['manifest_epoch'],expected_manifest_revision=receipt['manifest_revision'],operation_id='undo-after-edit'))
    assert caught.value.detail['code']=='undo_changed'
    db.rollback();assert first.content=='Later private source text' and first.chapter_number==-10


def test_exact_progress_receipt_replay_survives_renumber_but_new_old_address_cannot_save(db,test_user,case):
    from app.services.reading_progress_service import save_reading_progress
    from app.services.chapter_identity_service import identity
    novel,first,_,_=case
    captured={f'expected_{key}':value for key,value in identity(first).items()}
    captured['expected_content_version']=first.document['content_version']
    args=dict(user_id=test_user.id,chapter=first,position=10,percent=40,operation_id='progress-before-renumber',submitted_chapter_number=-2,**captured)
    receipt=save_reading_progress(db,**args)
    revision=receipt.revision
    result=preview(db,test_user,novel)
    asyncio.run(service.apply(db,test_user.id,novel.id,ManifestApplyInput(review_token=result['review_token'],operation_id='apply-progress')))
    replay=save_reading_progress(db,**args)
    assert replay.revision==revision and replay.chapter_number==-2
    db.rollback()
    with pytest.raises(HTTPException) as caught:save_reading_progress(db,**{**args,'operation_id':'new-stale-save'})
    assert caught.value.detail['code']=='chapter_manifest_changed'
    db.rollback()
    assert first.chapter_number==-10


@pytest.mark.parametrize('same_operation',[False,True])
def test_postgres_concurrent_apply_serializes_review_and_receipts(monkeypatch,same_operation):
    import os
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy import create_engine,text
    from sqlalchemy.orm import sessionmaker
    from config.database import Base
    from app.models import User,Library,Novel
    from app.services.chapter_identity_service import state_fields,manifest_state
    url=os.environ.get('NEXUS_MANIFEST_TEST_POSTGRES_URL')
    if not url:pytest.skip('Owned manifest PostgreSQL required')
    assert '/nexus_manifest_novel' in url
    admin=create_engine(url);schema='chapter_review_'+uuid4().hex
    with admin.begin() as c:c.execute(text(f'CREATE SCHEMA {schema}'))
    engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
    factory=sessionmaker(bind=engine)
    try:
        Base.metadata.create_all(engine)
        with factory() as db:
            user=User(username='chapter-review-owner',password='unused');db.add(user);db.flush()
            library=Library(user_id=user.id,name='Private');db.add(library);db.flush()
            novel=Novel(library_id=library.id,title='Concurrent original',metadata_id=123,site='royalroad',novel_site='royalroad',site_story_id=81)
            db.add(novel);db.flush()
            chapter=Chapter(novel_id=novel.id,chapter_number=-2,site_chapter_id=100,content='Private original',document=from_text('Private original'))
            db.add(chapter);db.commit()
            user_id,novel_id=user.id,novel.id
            manifest=ChapterManifestSnapshot(novel_id=123,manifest_key=str(uuid4()),revision='1'*64,fingerprint='2'*64,identity_kind='stable_source_id',total=1,
                source={'site':'royalroad','story_id':81,'source_url':'https://www.royalroad.com/fiction/81'},items=[dict(id=1,chapter_key=str(uuid4()),site='royalroad',story_id=81,chapter_id=100,chapter_number=7,title='Original',url='https://www.royalroad.com/fiction/81/chapter/100',category='story',word_count=10,identity_kind='stable_source_id')])
            barrier=Barrier(2);concurrent=[False]
            async def fetch(*args,**kwargs):
                if concurrent[0]:barrier.wait(timeout=10)
                return manifest
            monkeypatch.setattr(service.metadata_client,'get_chapter_manifest',fetch)
            monkeypatch.setitem(sys.modules,'app.services.chapter_topology_guards',SimpleNamespace(TOPOLOGY_GUARDS_COMPLETE=True,require_complete_guards=lambda *_:None))
            header=state_fields(manifest_state(db,novel_id))
            result=asyncio.run(service.preview(db,user_id,novel_id,ManifestPreviewInput(**{f'expected_{key}':v for key,v in header.items()})))
        concurrent[0]=True
        def run(index):
            with factory() as db:
                try:
                    receipt=asyncio.run(service.apply(db,user_id,novel_id,ManifestApplyInput(review_token=result['review_token'],operation_id='concurrent' if same_operation else f'concurrent-{index}')))
                    return 200,receipt
                except HTTPException as exc:
                    db.rollback();return exc.status_code,exc.detail
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(run,range(2)))
        assert sorted(item[0] for item in results)==([200,200] if same_operation else [200,409])
        if same_operation:assert results[0][1]==results[1][1]
        with factory() as db:
            from app.models.chapter_manifest import ChapterManifestOperation
            assert db.query(ChapterManifestOperation).count()==1
            assert db.query(Chapter).filter_by(novel_id=novel_id).one().chapter_number==7
    finally:
        engine.dispose()
        with admin.begin() as c:c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        admin.dispose()


def test_incomplete_ancillary_enrollment_is_visible_and_blocks_mutation(db,test_user,case,monkeypatch):
    novel,first,_,_=case
    monkeypatch.setitem(sys.modules,'app.services.chapter_topology_guards',SimpleNamespace(TOPOLOGY_GUARDS_COMPLETE=False,require_complete_guards=lambda *_:None))
    result=preview(db,test_user,novel)
    assert not result['can_apply']
    assert 'topology_guards_incomplete' in {row['code'] for row in result['blocked_reasons']}
    with pytest.raises(HTTPException) as caught:asyncio.run(service.apply(db,test_user.id,novel.id,ManifestApplyInput(review_token=result['review_token'],operation_id='not-enrolled')))
    assert caught.value.status_code==503
    db.rollback();assert first.chapter_number==-2


def test_inferred_history_needs_per_chapter_review_and_never_mints_strong_proof(db,test_user,case):
    from datetime import datetime
    from app.models.reading_history import ReadingHistory
    novel,first,_,remote=case
    history=ReadingHistory(user_id=test_user.id,novel_id=novel.id,chapter_key=first.chapter_key,chapter_number=-2,reading_date=datetime(2025,2,14),max_percent=100,identity_inferred=True)
    db.add(history);db.commit()
    result=preview(db,test_user,novel)
    assert not result['can_apply'] and result['counts']['inferred_anchors']==1
    assert 'inferred_anchor_confirmation_required' in {item['code'] for item in result['blocked_reasons']}
    result=preview(db,test_user,novel,mappings=[dict(chapter_key=first.chapter_key,metadata_chapter_key=remote.items[0]['chapter_key'],confirm_inferred_anchors=True)])
    assert result['can_apply']
    asyncio.run(service.apply(db,test_user.id,novel.id,ManifestApplyInput(review_token=result['review_token'],operation_id='review-inferred')))
    db.refresh(history)
    assert history.chapter_number==-2 and history.max_percent==100 and history.reading_date==datetime(2025,2,14)
    assert history.identity_inferred and history.verified_percent==0 and history.verified_content_version is None


# Reuse established authenticated HTTP fixtures; these exercise mounted routes.
from tests.routes.conftest import client,auth_headers  # noqa: E402,F401


def test_http_manifest_and_archived_notes_never_retarget_reused_number(client,db,test_user,case,auth_headers):
    from app.models.reading_annotation import ReadingAnnotation
    novel,first,_,_=case
    key=first.chapter_key;number=first.chapter_number
    note=ReadingAnnotation(user_id=test_user.id,novel_id=novel.id,chapter_id=first.id,note='Private note',annotation_type='note')
    db.add(note);db.commit()
    first.archived=True;db.flush()
    replacement=Chapter(novel_id=novel.id,chapter_number=number,content='Replacement must not inherit note',document=from_text('Replacement must not inherit note'))
    db.add(replacement);db.commit()
    response=client.get(f'/chapter/annotations/{novel.id}',headers=auth_headers)
    assert response.status_code==200,response.text
    annotation=response.json()[0]
    assert annotation['chapter_key']==key and annotation['archived'] and not annotation['identity_unresolved']
    content=client.get(f'/chapter/key/{novel.id}/{key}/content',headers=auth_headers)
    assert content.status_code==200 and 'Untouched original' in content.json()['content']
    wrong=client.get(f'/chapter/content/library/{novel.library_id}/{novel.id}/{number}',params={'expected_chapter_key':key},headers=auth_headers)
    assert wrong.status_code==409 and wrong.json()['detail']['code']=='chapter_manifest_changed'
    state=client.get(f'/chapter/novel/{novel.id}/manifest-state',params={'limit':1},headers=auth_headers)
    assert state.status_code==200,state.text
    assert state.json()['items'][0]['chapter_key']==replacement.chapter_key
    assert state.json()['has_more']
    second=client.get(f'/chapter/novel/{novel.id}/manifest-state',params={'cursor':state.json()['next_cursor'],'expected_manifest_epoch':state.json()['manifest_epoch'],'expected_manifest_revision':state.json()['manifest_revision'],'limit':1},headers=auth_headers)
    assert second.status_code==200 and second.json()['items'][0]['chapter_number']==7


def test_http_foreign_manifest_key_and_review_history_are_not_shared(client,db,test_user,test_library,case):
    from app.models import User
    from tests.auth_helpers import bearer_headers
    novel,first,_,_=case
    result=preview(db,test_user,novel)
    foreign=User(username='foreign-manifest-reader',password='unused');db.add(foreign);db.commit()
    headers=bearer_headers(foreign.id,db)
    for suffix in ('manifest-state','manifest/reviews',f'manifest/reviews/{result["review_id"]}'):
        assert client.get(f'/chapter/novel/{novel.id}/{suffix}',headers=headers).status_code==404
    assert client.get(f'/chapter/key/{novel.id}/{first.chapter_key}/content',headers=headers).status_code==404


def test_ingest_only_initial_or_proven_append_and_never_rebinds_number(db,test_user,case):
    from copy import deepcopy
    novel,first,second,remote=case
    remote.items[0]['chapter_number']=-2;remote.items[1]['chapter_number']=7
    assert service.ingest_metadata_snapshot(db,novel,remote)==[];db.commit()
    assert first.metadata_chapter_key==remote.items[0]['chapter_key']
    third=deepcopy(remote.items[1]);third.update(id=3,chapter_key=str(uuid4()),chapter_number=99,chapter_id=103,url='https://www.royalroad.com/fiction/81/chapter/103')
    remote.items.append(third);object.__setattr__(remote,'total',3)
    added=service.ingest_metadata_snapshot(db,novel,remote);db.commit()
    assert len(added)==1 and added[0].chapter_number==99 and added[0].metadata_chapter_key==third['chapter_key']
    remote.items[0]['chapter_number']=0
    with pytest.raises(HTTPException) as caught:service.ingest_metadata_snapshot(db,novel,remote)
    assert caught.value.detail['code']=='chapter_review_required'
    db.rollback();assert first.chapter_number==-2 and first.content=='Untouched original 0'


def test_unknown_unbound_manifest_requires_review_even_same_number_and_title(db,test_user,case):
    novel,first,_,remote=case
    for item,number in zip(remote.items,(-2,7)):
        item['chapter_number']=number;item['identity_kind']='unknown'
    with pytest.raises(HTTPException) as caught:service.ingest_metadata_snapshot(db,novel,remote)
    assert caught.value.detail['code']=='chapter_review_required'
    db.rollback();assert first.metadata_chapter_key is None


def test_review_additions_have_real_keys_and_undo_preserves_archived_lifecycle(db,test_user,case):
    from copy import deepcopy
    novel,first,_,remote=case
    addition=deepcopy(remote.items[-1]);addition.update(id=3,chapter_key=str(uuid4()),chapter_id=103,chapter_number=99,url='https://www.royalroad.com/fiction/81/chapter/103')
    remote.items.append(addition);object.__setattr__(remote,'total',3)
    result=preview(db,test_user,novel)
    receipt=asyncio.run(service.apply(db,test_user.id,novel.id,ManifestApplyInput(review_token=result['review_token'],operation_id='append-apply')))
    created=db.query(Chapter).filter_by(novel_id=novel.id,chapter_number=99).one();key=created.chapter_key
    assert key is not None and created.metadata_chapter_key==addition['chapter_key']
    service.undo(db,test_user.id,novel.id,result['review_id'],ManifestUndoInput(expected_revision=receipt['revision'],expected_manifest_epoch=receipt['manifest_epoch'],expected_manifest_revision=receipt['manifest_revision'],operation_id='append-undo'))
    assert db.query(Chapter).filter_by(chapter_key=key).first() is None
    archived=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(chapter_key=key).one()
    assert archived.archived and archived.chapter_number==99
    assert first.chapter_number==-2


def test_reapply_after_undo_reactivates_exact_pristine_placeholder_uuid(db,test_user,case):
    from copy import deepcopy
    novel,_,_,remote=case
    addition=deepcopy(remote.items[-1]);addition.update(id=3,chapter_key=str(uuid4()),chapter_id=103,chapter_number=99,url='https://www.royalroad.com/fiction/81/chapter/103')
    remote.items.append(addition);object.__setattr__(remote,'total',3)
    keys=[]
    for index in range(2):
        result=preview(db,test_user,novel)
        assert result['can_apply']
        ack=asyncio.run(service.apply(db,test_user.id,novel.id,ManifestApplyInput(review_token=result['review_token'],operation_id=f'cycle-{index}')))
        keys.append(db.query(Chapter.chapter_key).filter_by(novel_id=novel.id,chapter_number=99).scalar())
        service.undo(db,test_user.id,novel.id,result['review_id'],ManifestUndoInput(expected_revision=ack['revision'],expected_manifest_epoch=ack['manifest_epoch'],expected_manifest_revision=ack['manifest_revision'],operation_id=f'cycle-undo-{index}'))
    assert keys[0]==keys[1] and keys[0] is not None
    assert db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(novel_id=novel.id,metadata_chapter_key=addition['chapter_key']).count()==1


def test_full_anchor_snapshot_and_canonical_completion_survive_apply_undo(db,test_user,case):
    from app.services.reading_progress_service import save_reading_progress
    from app.services.chapter_identity_service import identity
    from app.services.chapter_document import from_html
    from app.services.reading_run_service import current_run,mark_complete
    from app.models.reading_history import ReadingHistory
    from app.models.reading_annotation import ReadingAnnotation
    from app.models.reading_run import ReadingRunEvent
    from app.models.reading_continuity import ReadingContinuity
    novel,first,second,_=case
    first.document=from_html('<p>A😀 <em>nested words</em> finish.</p>');first.content=first.document['plain_text'];db.commit()
    def save(chapter,percent,position,offset):
        expected={f'expected_{key}':v for key,v in identity(chapter).items()}
        return save_reading_progress(db,user_id=test_user.id,chapter=chapter,position=position,percent=percent,
            block_id=chapter.document['blocks'][0]['id'],text_offset=offset,text_quote='😀' if chapter==first else 'original',
            content_version=chapter.document['content_version'],expected_content_version=chapter.document['content_version'],**expected)
    save(first,100,30,3);point=save(second,40,123,2)
    note=ReadingAnnotation(user_id=test_user.id,novel_id=novel.id,chapter_id=first.id,annotation_type='highlight',block_id=first.document['blocks'][0]['id'],text_offset=1,text_quote='😀',locator_content_version=first.document['content_version'])
    db.add(note);run=current_run(db,test_user.id,novel.id,point);mark_complete(db,run);db.commit()
    original=dict(key=point.chapter_key,number=point.chapter_number,furthest=point.furthest_chapter_key,position=point.position,
        block=point.block_id,offset=point.text_offset,version=point.source_content_version,run=point.reading_run_key,revision=point.revision)
    historical=[(r.id,r.chapter_number,r.chapter_key,r.reading_date,r.max_percent,r.verified_percent,r.verified_content_version) for r in db.query(ReadingHistory).filter_by(novel_id=novel.id)]
    events=db.query(ReadingRunEvent).count();completed=db.query(ReadingContinuity).filter_by(completed=True).count()
    result=preview(db,test_user,novel)
    ack=asyncio.run(service.apply(db,test_user.id,novel.id,ManifestApplyInput(review_token=result['review_token'],operation_id='full-anchor-apply')))
    db.refresh(point);db.refresh(note);db.refresh(run)
    assert (point.chapter_key,point.chapter_number,point.furthest_chapter_key,point.furthest_chapter_number)==(original['key'],30,original['furthest'],30)
    assert (point.position,point.block_id,point.text_offset,point.source_content_version,point.reading_run_key)==(123,original['block'],2,original['version'],original['run'])
    assert run.progress_snapshot['chapter_key']==second.chapter_key and run.progress_snapshot['chapter_number']==30
    assert note.chapter_key==first.chapter_key and note.chapter_number==-2 and note.text_quote=='😀'
    assert historical==[(r.id,r.chapter_number,r.chapter_key,r.reading_date,r.max_percent,r.verified_percent,r.verified_content_version) for r in db.query(ReadingHistory).filter_by(novel_id=novel.id)]
    assert db.query(ReadingRunEvent).count()==events and db.query(ReadingContinuity).filter_by(completed=True).count()==completed==1
    applied_revision=point.revision
    service.undo(db,test_user.id,novel.id,result['review_id'],ManifestUndoInput(expected_revision=ack['revision'],expected_manifest_epoch=ack['manifest_epoch'],expected_manifest_revision=ack['manifest_revision'],operation_id='full-anchor-undo'))
    db.refresh(point);db.refresh(note)
    assert point.chapter_key==original['key'] and point.chapter_number==7 and point.furthest_chapter_number==7
    assert point.position==123 and point.block_id==original['block'] and point.text_offset==2
    assert point.revision>applied_revision>original['revision']
    assert note.text_quote=='😀' and note.locator_content_version==first.document['content_version']
    assert db.query(ReadingRunEvent).count()==events and db.query(ReadingContinuity).filter_by(completed=True).count()==1


def test_unknown_saved_anchor_requires_explicit_resolution_and_undo_restores_unknown(db,test_user,case):
    from app.models.reading_progress import ReadingProgress
    novel,first,_,remote=case
    point=ReadingProgress(user_id=test_user.id,novel_id=novel.id,chapter_number=99,chapter_key=None,current_identity_inferred=True,
        position=45,percent=40,furthest_chapter_number=0,furthest_percent=0)
    db.add(point);db.commit()
    result=preview(db,test_user,novel)
    assert not result['can_apply'] and 'current_anchor_unresolved' in {r['code'] for r in result['blocked_reasons']}
    assert result['anchors'][0]['chapter_number']==99 and not result['anchors'][0]['resolved']
    result=preview(db,test_user,novel,resolve_current_chapter_key=first.chapter_key,mappings=[dict(chapter_key=first.chapter_key,metadata_chapter_key=remote.items[0]['chapter_key'],confirm_inferred_anchors=True)])
    assert result['can_apply']
    ack=asyncio.run(service.apply(db,test_user.id,novel.id,ManifestApplyInput(review_token=result['review_token'],operation_id='resolve-unknown')))
    db.refresh(point);assert point.chapter_key==first.chapter_key and point.chapter_number==-10 and point.current_identity_inferred
    assert point.source_content_version is None and point.percent==40
    service.undo(db,test_user.id,novel.id,result['review_id'],ManifestUndoInput(expected_revision=ack['revision'],expected_manifest_epoch=ack['manifest_epoch'],expected_manifest_revision=ack['manifest_revision'],operation_id='undo-unknown'))
    db.refresh(point);assert point.chapter_key is None and point.chapter_id is None and point.chapter_number==99
    assert point.current_identity_inferred and point.position==45


def test_ingest_hydrates_database_keys_in_bounded_batches_before_commit(db,test_user,test_library):
    from sqlalchemy import event
    from app.models import Novel
    from app.services.chapter_identity_service import manifest_state
    novel=Novel(title='Pristine large manifest',library_id=test_library.id,metadata_id=124);db.add(novel);db.commit()
    remote=ChapterManifestSnapshot(novel_id=124,manifest_key=str(uuid4()),revision='1'*64,fingerprint='2'*64,identity_kind='unknown',total=501,
        source={'site':'fanfiction','story_id':81,'source_url':'https://www.fanfiction.net/s/81'},items=[dict(id=index+1,chapter_key=str(uuid4()),site='fanfiction',story_id=81,chapter_id=index+1,chapter_number=index*3-2000,title=f'Original {index}',url=f'https://www.fanfiction.net/s/81/{index+1}',category='story',word_count=10,identity_kind='positional') for index in range(501)])
    projections=[]
    def observe(_conn,_cursor,statement,parameters,_context,_many):
        if 'chapters.chapter_key AS chapters_chapter_key' in statement and 'chapters.id IN (' in statement:
            projections.append(len(parameters))
    event.listen(db.get_bind(),'before_cursor_execute',observe)
    try:
        created=service.ingest_metadata_snapshot(db,novel,remote)
        assert len(created)==501 and len({row.chapter_key for row in created})==501
        from uuid import UUID
        assert all(str(UUID(row.chapter_key))==row.chapter_key for row in created)
        assert projections==[500,1]
        assert manifest_state(db,novel.id).revision==501
    finally:event.remove(db.get_bind(),'before_cursor_execute',observe)
    db.rollback()
    assert db.query(Chapter).filter_by(novel_id=novel.id).count()==0


def test_postgres_ingest_returns_real_key_and_current_state_before_commit(monkeypatch):
    import os
    from sqlalchemy import create_engine,text
    from sqlalchemy.orm import sessionmaker
    from config.database import Base
    from app.models import User,Library,Novel
    from app.services.chapter_identity_service import manifest_state
    url=os.environ.get('NEXUS_MANIFEST_TEST_POSTGRES_URL')
    if not url:pytest.skip('Owned manifest PostgreSQL required')
    assert '/nexus_manifest_novel' in url
    admin=create_engine(url);schema='chapter_ingest_'+uuid4().hex
    with admin.begin() as c:c.execute(text(f'CREATE SCHEMA {schema}'))
    engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
    try:
        Base.metadata.create_all(engine)
        with sessionmaker(bind=engine)() as db:
            user=User(username='ingest-owner',password='unused');db.add(user);db.flush()
            library=Library(user_id=user.id,name='Private');db.add(library);db.flush()
            novel=Novel(library_id=library.id,title='Original',metadata_id=123);db.add(novel);db.commit()
            remote=ChapterManifestSnapshot(novel_id=123,manifest_key=str(uuid4()),revision='1'*64,fingerprint='2'*64,identity_kind='stable_source_id',total=1,
                source={'site':'royalroad','story_id':81,'source_url':'https://www.royalroad.com/fiction/81'},items=[dict(id=1,chapter_key=str(uuid4()),site='royalroad',story_id=81,chapter_id=100,chapter_number=-2,title='Original',url='https://www.royalroad.com/fiction/81/chapter/100',category='story',word_count=10,identity_kind='stable_source_id')])
            created=service.ingest_metadata_snapshot(db,novel,remote)
            from uuid import UUID
            assert str(UUID(created[0].chapter_key))==created[0].chapter_key
            assert manifest_state(db,novel.id).revision==1
            db.rollback();assert db.query(Chapter).count()==0
    finally:
        engine.dispose()
        with admin.begin() as c:c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
        admin.dispose()


def test_immutable_work_uuid_does_not_hide_source_namespace_drift(db,test_user,case):
    novel,first,_,remote=case
    remote.items[0]['chapter_number']=-2;remote.items[1]['chapter_number']=7
    service.ingest_metadata_snapshot(db,novel,remote);db.commit()
    before=dict(db.get(ChapterManifestState,novel.id).metadata_source)
    remote.source['source_url']='https://www.royalroad.com/fiction/81/new-canonical-path'
    with pytest.raises(HTTPException) as caught:service.ingest_metadata_snapshot(db,novel,remote)
    assert caught.value.detail['code']=='chapter_review_required'
    db.rollback();assert db.get(ChapterManifestState,novel.id).metadata_source==before
    result=preview(db,test_user,novel)
    assert all(row['requires_content_review'] for row in result['items']['items'])
    assert result['remote']['source']==remote.source
    assert first.content=='Untouched original 0'


def test_reviewed_namespace_change_updates_consent_source_and_undo_restores_proof(db,test_user,case):
    from app.services.chapter_identity_service import identity
    from app.services.reading_progress_service import save_reading_progress
    from app.models.chapter_read_receipt import ChapterReadReceipt
    from app.models.reading_history import ReadingHistory
    novel,first,_,remote=case
    novel.url='nexus-local:original-user-input';novel.source_url=remote.source['source_url']
    remote.items[0]['chapter_number']=-2;remote.items[1]['chapter_number']=7
    service.ingest_metadata_snapshot(db,novel,remote);db.commit()
    expected={f'expected_{key}':v for key,v in identity(first).items()}
    point=save_reading_progress(db,user_id=test_user.id,chapter=first,position=30,percent=100,
        content_version=first.document['content_version'],expected_content_version=first.document['content_version'],**expected)
    receipt=db.query(ChapterReadReceipt).filter_by(chapter_key=first.chapter_key).one()
    assert receipt.completed and not receipt.requires_review
    assert not db.get(ChapterManifestState,novel.id).ao3_material
    old_source=dict(remote.source)
    remote.source.update(site='archive',story_id=808,source_url='https://archiveofourown.org/works/808')
    for item in remote.items:item.update(site='archive',story_id=808,url=f'https://archiveofourown.org/works/808/chapters/{item["chapter_id"]}')
    result=preview(db,test_user,novel)
    assert result['can_apply'] and all(item['requires_content_review'] for item in result['items']['items'])
    ack=asyncio.run(service.apply(db,test_user.id,novel.id,ManifestApplyInput(review_token=result['review_token'],operation_id='namespace-reviewed')))
    db.refresh(novel);db.refresh(receipt);db.refresh(point)
    assert (novel.site,novel.novel_site,novel.story_id,novel.site_story_id,novel.source_url)==('archive','archive',808,808,remote.source['source_url'])
    assert db.get(ChapterManifestState,novel.id).ao3_material
    assert novel.url=='nexus-local:original-user-input' and point.source_content_version is None
    assert receipt.requires_review and receipt.completed
    history=db.query(ReadingHistory).filter_by(chapter_key=first.chapter_key).one()
    assert history.max_percent==100 and history.verified_percent==0
    assert first.content=='Untouched original 0'
    service.undo(db,test_user.id,novel.id,result['review_id'],ManifestUndoInput(expected_revision=ack['revision'],expected_manifest_epoch=ack['manifest_epoch'],expected_manifest_revision=ack['manifest_revision'],operation_id='namespace-undo'))
    db.refresh(novel);db.refresh(receipt);db.refresh(point);db.refresh(history)
    assert (novel.site,novel.site_story_id,novel.source_url)==('royalroad',81,old_source['source_url'])
    assert novel.url=='nexus-local:original-user-input' and not receipt.requires_review
    assert point.source_content_version==first.document['content_version'] and history.verified_percent==100
    assert db.get(ChapterManifestState,novel.id).ao3_material
    from sqlalchemy import text
    with pytest.raises(Exception):db.execute(text('UPDATE chapter_manifest_states SET ao3_material=false WHERE novel_id=:id'),{'id':novel.id})
    db.rollback()


def test_stable_initial_binding_enrichment_preserves_legacy_pre_topology_gate(db,test_user,case):
    novel,_,_,remote=case
    remote.items[0]['chapter_number']=-2;remote.items[1]['chapter_number']=7
    # The fixture deliberately changed ordinals during setup; model a migrated
    # installation whose original topology predates the new revision counter.
    # Use a fresh pristine row instead of clearing the irreversible true flag.
    from app.models import Novel
    fresh=Novel(title='Legacy stable copy',library_id=novel.library_id,metadata_id=124,site='royalroad',novel_site='royalroad',site_story_id=81)
    db.add(fresh);db.flush()
    original=Chapter(novel_id=fresh.id,chapter_number=-2,site_chapter_id=100,content='Retained legacy original')
    db.add(original);db.commit()
    from dataclasses import replace
    snapshot=replace(remote,novel_id=124,total=1,items=[remote.items[0]])
    assert not db.get(ChapterManifestState,fresh.id).identity_required
    service.ingest_metadata_snapshot(db,fresh,snapshot);db.commit()
    assert not db.get(ChapterManifestState,fresh.id).identity_required
    assert original.content=='Retained legacy original'
    original.chapter_number=-3;db.commit()
    assert db.get(ChapterManifestState,fresh.id).identity_required


def test_archived_original_requires_explicit_mapping_and_restores_same_uuid_with_notes(db,test_user,case):
    from datetime import datetime
    from app.services.reading_progress_service import save_reading_progress
    from app.services.chapter_identity_service import identity
    from app.models.reading_annotation import ReadingAnnotation
    from app.models.chapter_read_receipt import ChapterReadReceipt
    from app.models.reading_history import ReadingHistory
    novel,first,second,remote=case
    remote.items[0]['chapter_number']=-2;remote.items[1]['chapter_number']=7
    service.ingest_metadata_snapshot(db,novel,remote);db.commit()
    expected={f'expected_{key}':value for key,value in identity(first).items()}
    point=save_reading_progress(db,user_id=test_user.id,chapter=first,position=45,percent=100,
        content_version=first.document['content_version'],expected_content_version=first.document['content_version'],**expected)
    note=ReadingAnnotation(user_id=test_user.id,novel_id=novel.id,chapter_id=first.id,annotation_type='note',note='Keep this original',locator_content_version=first.document['content_version'])
    db.add(note);db.commit();key=first.chapter_key;body=first.content
    archived_at=datetime(2025,2,14,12,30)
    first.archived=True;first.archived_at=archived_at;db.commit()
    remote.items[0]['chapter_number']=-10
    result=preview(db,test_user,novel)
    assert not result['can_apply'] and result['counts']['unmapped']==0
    codes={item['code'] for item in result['blocked_reasons']}
    assert {'archived_original_requires_mapping','current_anchor_archived','furthest_anchor_archived'}<=codes
    archived_item=next(item for item in result['items']['items'] if item['chapter_key']==key)
    assert archived_item['archived'] and archived_item['decision']=='unlisted'
    result=preview(db,test_user,novel,mappings=[dict(chapter_key=key,metadata_chapter_key=remote.items[0]['chapter_key'])])
    assert result['can_apply'] and result['counts']['restored_chapters']==1
    ack=asyncio.run(service.apply(db,test_user.id,novel.id,ManifestApplyInput(review_token=result['review_token'],operation_id='restore-preserved-original')))
    db.refresh(first);db.refresh(point);db.refresh(note)
    assert first.chapter_key==key and not first.archived and first.content==body and first.chapter_number==-10
    assert point.chapter_key==key and point.chapter_number==-10 and point.position==45
    assert note.chapter_key==key and note.chapter_number==-2 and note.note=='Keep this original'
    assert db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(novel_id=novel.id).count()==2
    assert not db.query(ChapterReadReceipt).filter_by(chapter_key=key).one().requires_review
    assert db.query(ReadingHistory).filter_by(chapter_key=key).one().verified_percent==100
    service.undo(db,test_user.id,novel.id,result['review_id'],ManifestUndoInput(expected_revision=ack['revision'],expected_manifest_epoch=ack['manifest_epoch'],expected_manifest_revision=ack['manifest_revision'],operation_id='undo-original-restoration'))
    preserved=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(chapter_key=key).one()
    assert preserved.archived and preserved.archived_at==archived_at and preserved.chapter_number==-2 and preserved.content==body
    assert db.query(Chapter).filter_by(chapter_key=key).first() is None
    assert service.keyed_content(db,test_user.id,novel.id,key)['content']==body


def test_initial_ao3_ingest_sets_sticky_private_provenance(db,test_user,case):
    novel,first,second,remote=case
    novel.site=novel.novel_site='archive';novel.site_story_id=81
    remote.source.update(site='archive',source_url='https://archiveofourown.org/works/81')
    for chapter,item in zip((first,second),remote.items):
        item.update(site='archive',chapter_number=chapter.chapter_number,url=f'https://archiveofourown.org/works/81/chapters/{item["chapter_id"]}')
    db.commit()
    assert not db.get(ChapterManifestState,novel.id).ao3_material
    service.ingest_metadata_snapshot(db,novel,remote);db.commit()
    assert db.get(ChapterManifestState,novel.id).ao3_material
