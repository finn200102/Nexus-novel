"""Only reviewed, authoritative absence can archive a private original."""
# ruff: noqa: F811
import asyncio
from dataclasses import replace
from uuid import uuid4
import pytest
from fastapi import HTTPException
from app.models import Chapter,ReadingAnnotation
from app.models.chapter_manifest import ChapterManifestState
from app.models.chapter_read_receipt import ChapterReadReceipt
from app.models.reading_progress import ReadingProgress
from app.schemas.chapter_manifest import ManifestApplyInput,ManifestUndoInput
from app.services import chapter_manifest_service as service
from tests.contracts.test_chapter_manifest_reviews import case,preview  # noqa:F401
from tests.routes.conftest import db,test_user,test_library  # noqa:F401


@pytest.fixture
def absent(db,case,monkeypatch):
    novel,first,second,remote=case
    novel.source_url=remote.source['source_url'];novel.story_id=81
    state=db.get(ChapterManifestState,novel.id)
    state.metadata_source=dict(remote.source);state.metadata_manifest_key=remote.manifest_key
    for chapter,item in zip((first,second),remote.items):
        chapter.metadata_manifest_key=remote.manifest_key;chapter.metadata_chapter_key=item['chapter_key']
    db.commit()
    accepted=replace(remote,items=remote.items[1:],total=1,source_complete=True,deletion_authoritative=True,
        source_capture_id=str(uuid4()),source_authority_kind='adapter_stable')
    async def fetch(*args,**kwargs):return accepted
    monkeypatch.setattr(service.metadata_client,'get_chapter_manifest',fetch)
    return novel,first,second,accepted


def apply(db,user,novel,review,operation='archive-original'):
    return asyncio.run(service.apply(db,user.id,novel.id,ManifestApplyInput(review_token=review['review_token'],operation_id=operation)))


def test_archive_preserves_original_note_and_receipt_and_undo_restores(db,test_user,absent):
    novel,first,second,_=absent
    key,body=first.chapter_key,first.content
    note=ReadingAnnotation(user_id=test_user.id,novel_id=novel.id,chapter_id=first.id,annotation_type='note',quote='Untouched',note='Private original')
    receipt=ChapterReadReceipt(user_id=test_user.id,chapter_id=first.id,content_version=first.document['content_version'],completed=True)
    db.add_all([note,receipt]);db.commit();note_id,receipt_id=note.id,receipt.id
    result=preview(db,test_user,novel,archive_chapter_keys=[key])
    assert result['can_apply'] and result['counts']['newly_archived_chapters']==1
    assert result['counts']['unmapped']==0
    archived=next(item for item in result['items']['items'] if item['chapter_key']==key)
    assert archived['decision']=='archive' and archived['to_number'] is None
    assert archived['can_archive'] and archived['archive_blocked_reason'] is None
    ack=apply(db,test_user,novel,result)
    db.expire_all();assert first.archived and first.archived_at and first.chapter_key==key and first.content==body
    assert db.get(ReadingAnnotation,note_id).note=='Private original'
    assert db.get(ChapterReadReceipt,receipt_id).completed
    assert {c.chapter_key for c in db.query(Chapter).filter_by(novel_id=novel.id)}=={second.chapter_key}
    assert service.keyed_content(db,test_user.id,novel.id,key)['content']==body
    current=service.review_view(db,test_user.id,novel.id,result['review_id'])
    assert current['can_undo']
    undo=ManifestUndoInput(expected_revision=current['revision'],expected_manifest_epoch=current['manifest_epoch'],expected_manifest_revision=current['manifest_revision'],operation_id='undo-archive')
    service.undo(db,test_user.id,novel.id,result['review_id'],undo)
    db.expire_all();assert not first.archived and first.archived_at is None and first.content==body
    assert apply(db,test_user,novel,result)==ack
    db.expire_all();assert not first.archived


@pytest.mark.parametrize('field,value',[
    ('source_complete',False),('deletion_authoritative',False),('complete',False),
    ('source_capture_id',None),('source_authority_kind',None),('source_authority_kind','raw_observation')])
def test_partial_or_unaccepted_source_never_authorizes_archive(db,test_user,absent,monkeypatch,field,value):
    novel,first,_,remote=absent
    async def fetch(*args,**kwargs):return replace(remote,**{field:value})
    monkeypatch.setattr(service.metadata_client,'get_chapter_manifest',fetch)
    with pytest.raises(HTTPException) as caught:preview(db,test_user,novel,archive_chapter_keys=[first.chapter_key])
    assert caught.value.status_code==422 and caught.value.detail['code']=='source_absence_unproven'
    db.rollback();assert not first.archived


@pytest.mark.parametrize('change',['namespace','unbound','present_uuid','present_stable_id','duplicate','foreign','overlap'])
def test_archive_rejects_unproven_or_still_present_identity(db,test_user,absent,monkeypatch,change):
    novel,first,second,remote=absent
    keys=[first.chapter_key];kwargs={}
    if change=='namespace':
        remote=replace(remote,source={**remote.source,'source_url':'https://www.royalroad.com/fiction/82'})
    elif change=='unbound':first.metadata_chapter_key=None;db.commit()
    elif change in ('present_uuid','present_stable_id'):
        item=dict(remote.items[0]);item['chapter_id']=first.site_chapter_id
        if change=='present_uuid':item['chapter_key']=first.metadata_chapter_key
        remote=replace(remote,items=[item])
    elif change=='duplicate':keys*=2
    elif change=='foreign':keys=[str(uuid4())]
    else:kwargs['mappings']=[{'chapter_key':first.chapter_key,'metadata_chapter_key':remote.items[0]['chapter_key']}]
    async def fetch(*args,**kw):return remote
    monkeypatch.setattr(service.metadata_client,'get_chapter_manifest',fetch)
    with pytest.raises(HTTPException) as caught:preview(db,test_user,novel,archive_chapter_keys=keys,**kwargs)
    assert caught.value.status_code==422
    db.rollback();assert not first.archived and not second.archived


def test_archived_saved_positions_require_explicit_relocation_and_zero_locators(db,test_user,absent):
    novel,first,second,_=absent
    version=first.document['content_version']
    point=ReadingProgress(user_id=test_user.id,novel_id=novel.id,chapter_id=first.id,chapter_key=first.chapter_key,chapter_number=first.chapter_number,
        percent=80,position=500,furthest_chapter_key=first.chapter_key,furthest_chapter_number=first.chapter_number,furthest_percent=100,
        block_id='original',text_offset=5,text_quote='old',quote_prefix='before',quote_suffix='after',locator_content_version=version,
        locator_variant='original',source_content_version=version,furthest_content_version=version)
    db.add(point);db.commit()
    result=preview(db,test_user,novel,archive_chapter_keys=[first.chapter_key])
    assert not result['can_apply']
    assert {'current_anchor_archive_resolution_required','furthest_anchor_archive_resolution_required'}<={r['code'] for r in result['blocked_reasons']}
    # Destination retains its address here so no separate inferred-history move is involved.
    result=preview(db,test_user,novel,archive_chapter_keys=[first.chapter_key],
        resolve_current_chapter_key=second.chapter_key,resolve_furthest_chapter_key=second.chapter_key,
        mappings=[{'chapter_key':second.chapter_key,'metadata_chapter_key':second.metadata_chapter_key,'confirm_inferred_anchors':True}])
    assert result['can_apply'],result['blocked_reasons']
    assert all(a['relocated'] and a['percent']==0 and a['content_version'] is None for a in result['anchors'])
    assert {a['previous_percent'] for a in result['anchors']}=={80,100}
    assert all(a['previous_chapter_key']==first.chapter_key and a['previous_chapter_number']==first.chapter_number and a['chapter_number']==30 for a in result['anchors'])
    apply(db,test_user,novel,result)
    db.expire_all();assert point.chapter_key==second.chapter_key and point.furthest_chapter_key==second.chapter_key
    assert point.percent==point.furthest_percent==point.position==point.text_offset==0
    assert point.current_identity_inferred and point.furthest_identity_inferred
    assert all(getattr(point,field) is None for field in ('block_id','text_quote','quote_prefix','quote_suffix','locator_content_version','locator_variant','source_content_version','furthest_content_version'))
    current=service.review_view(db,test_user.id,novel.id,result['review_id'])
    service.undo(db,test_user.id,novel.id,result['review_id'],ManifestUndoInput(expected_revision=current['revision'],expected_manifest_epoch=current['manifest_epoch'],expected_manifest_revision=current['manifest_revision'],operation_id='undo-position'))
    db.expire_all();assert point.chapter_key==first.chapter_key and point.percent==80 and point.position==500 and point.block_id=='original'


def test_changed_source_capture_blocks_apply_before_archive(db,test_user,absent,monkeypatch):
    novel,first,_,remote=absent
    result=preview(db,test_user,novel,archive_chapter_keys=[first.chapter_key])
    async def fetch(*args,**kwargs):return replace(remote,source_capture_id=str(uuid4()))
    monkeypatch.setattr(service.metadata_client,'get_chapter_manifest',fetch)
    with pytest.raises(HTTPException) as caught:apply(db,test_user,novel,result)
    assert caught.value.status_code==409 and caught.value.detail['code']=='review_stale'
    db.rollback();assert not first.archived


def test_same_number_new_remote_uuid_invalidates_previous_read_proof(db,test_user,case,monkeypatch):
    novel,first,second,remote=case
    state=db.get(ChapterManifestState,novel.id);state.metadata_source=dict(remote.source);state.metadata_manifest_key=remote.manifest_key
    novel.source_url=remote.source['source_url']
    first.metadata_manifest_key=remote.manifest_key;first.metadata_chapter_key=str(uuid4())
    second.metadata_manifest_key=remote.manifest_key;second.metadata_chapter_key=remote.items[1]['chapter_key']
    remote.items[0]['chapter_number']=first.chapter_number
    receipt=ChapterReadReceipt(user_id=test_user.id,chapter_id=first.id,content_version=first.document['content_version'],completed=True)
    db.add(receipt);db.commit()
    result=preview(db,test_user,novel)
    assert result['can_apply']
    item=next(item for item in result['items']['items'] if item['chapter_key']==first.chapter_key)
    assert item['requires_content_review'] and item['from_number']==item['to_number']
    apply(db,test_user,novel,result)
    db.expire_all();assert receipt.requires_review and first.metadata_chapter_key==remote.items[0]['chapter_key']


def test_authoritative_absence_never_archives_without_an_explicit_choice(db,test_user,absent):
    novel,first,_,_=absent
    result=preview(db,test_user,novel)
    assert not result['can_apply'] and result['counts']['newly_archived_chapters']==0
    assert 'unmapped_local_chapters' in {r['code'] for r in result['blocked_reasons']}
    db.expire_all();assert not first.archived


def test_reviewed_positional_lineage_is_suggested_and_prevents_false_absence(db,test_user,absent,monkeypatch):
    from types import SimpleNamespace
    novel,first,second,remote=absent
    new=dict(remote.items[0],identity_kind='positional',chapter_id=999)
    revised=SimpleNamespace(**{**vars(remote),'items':[new],'source_authority_kind':'reviewed_mapping','source_review_id':str(uuid4()),
        'source_lineage':[{'capture_ordinal':0,'old_chapter_key':first.metadata_chapter_key,'new_chapter_key':new['chapter_key']}],
        'source_lineage_fingerprint':'d'*64})
    # Second original is absent too; leave it unmapped to show advisory candidates only.
    async def fetch(*args,**kwargs):return revised
    monkeypatch.setattr(service.metadata_client,'get_chapter_manifest',fetch)
    result=preview(db,test_user,novel)
    row=next(row for row in result['items']['items'] if row['chapter_key']==first.chapter_key)
    assert row['decision']=='needs_mapping' and row['metadata_chapter_key'] is None
    assert not row['can_archive'] and 'still present' in row['archive_blocked_reason']
    assert row['candidates'][0]['metadata_chapter_key']==new['chapter_key']
    assert not result['can_apply']
    with pytest.raises(HTTPException) as caught:preview(db,test_user,novel,archive_chapter_keys=[first.chapter_key])
    assert caught.value.detail['code']=='source_chapter_still_present'
    db.rollback();assert not first.archived and not second.archived


def test_new_lineage_fingerprint_invalidates_review_even_when_capture_is_same(db,test_user,absent,monkeypatch):
    from types import SimpleNamespace
    novel,first,_,remote=absent
    revised=SimpleNamespace(**{**vars(remote),'source_lineage':[],'source_lineage_fingerprint':'a'*64})
    async def fetch(*args,**kwargs):return revised
    monkeypatch.setattr(service.metadata_client,'get_chapter_manifest',fetch)
    result=preview(db,test_user,novel,archive_chapter_keys=[first.chapter_key])
    revised.source_lineage_fingerprint='b'*64
    with pytest.raises(HTTPException) as caught:apply(db,test_user,novel,result)
    assert caught.value.detail['code']=='review_stale'
    db.rollback();assert not first.archived
