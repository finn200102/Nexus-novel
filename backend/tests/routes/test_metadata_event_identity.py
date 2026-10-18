"""Metadata events wake proven append ingestion; numeric payloads never bind rows."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4
import asyncio
import pytest
from app.models import Novel,Chapter
from app.models.follow import UserNovelFollow
from app.models.download_job import ChapterDownloadJob
from app.models.update_event import NovelUpdateEvent
from app.models.metadata_webhook_delivery import MetadataWebhookDelivery
from app.services import metadata_event_ingestion as service,metadata_client


def setup(db,user,library,monkeypatch):
    novel=Novel(title='Source',library_id=library.id,metadata_id=17,novel_site='royalroad',site='royalroad',site_story_id=18,story_id=18,url='https://www.royalroad.com/fiction/18',source_url='https://www.royalroad.com/fiction/18')
    db.add(novel);db.flush()
    db.add(UserNovelFollow(user_id=user.id,novel_id=novel.id,state='reading',download_policy='next_n',download_count=3,notification_policy='immediate'))
    db.commit()
    items=[dict(id=n+10,chapter_key=str(uuid4()),site='royalroad',story_id=18,chapter_id=n+100,chapter_number=n,title=f'Part {n}',url=f'https://www.royalroad.com/fiction/18/chapter/{n+100}',category='story',word_count=12,identity_kind='stable_source_id') for n in (-2,0,7)]
    snapshot=metadata_client.ChapterManifestSnapshot(novel_id=17,manifest_key=str(uuid4()),revision='a'*64,fingerprint='b'*64,identity_kind='stable_source_id',total=3,source=dict(site='royalroad',story_id=18,source_url=novel.source_url),items=items)
    event=SimpleNamespace(event='source_refresh_completed',delivery_id=str(uuid4()),source_id=99,job_id='job',metadata_novel_id=17,site='royalroad',new_chapter_numbers=[999],chapters=[],manifest_proof=dict(protocol=1,manifest_key=snapshot.manifest_key,revision=snapshot.revision,fingerprint=snapshot.fingerprint,source=snapshot.source,chapters=[dict(chapter_key=items[-1]['chapter_key'],chapter_number=7)]))
    async def caps(*args,**kwargs):assert not db.in_transaction();return {'protocols':[1],'content_identity':True}
    async def manifest(*args,**kwargs):assert not db.in_transaction();assert kwargs['force_refresh'];return deepcopy(snapshot)
    monkeypatch.setattr(metadata_client,'_manifest_request',caps);monkeypatch.setattr(metadata_client,'get_chapter_manifest',manifest)
    return novel,event,snapshot


def run(db,event):return asyncio.run(service.receive_completed(db,event))


def test_wakeup_uses_fresh_signed_rows_not_numeric_payload_and_is_idempotent(db,test_user,test_library,monkeypatch):
    novel,event,snapshot=setup(db,test_user,test_library,monkeypatch)
    result=run(db,event);assert result['created_events']==1 and result['queued_downloads']==3
    chapters=db.query(Chapter).filter_by(novel_id=novel.id).order_by(Chapter.chapter_number).all()
    assert [r.chapter_number for r in chapters]==[-2,0,7]
    assert [r.metadata_chapter_key for r in chapters]==[r['chapter_key'] for r in snapshot.items]
    assert all(job.chapter_identity['metadata_chapter_key'] for job in db.query(ChapterDownloadJob))
    notice=db.query(NovelUpdateEvent).one();assert notice.chapter_count==3 and notice.first_chapter_number==-2
    assert run(db,event)['state']=='duplicate' and db.query(ChapterDownloadJob).count()==3


@pytest.mark.parametrize('problem',['replacement','source','fingerprint','legacy_peer'])
def test_changed_reference_or_old_peer_preserves_original_and_durably_requests_review(db,test_user,test_library,monkeypatch,problem):
    novel,event,snapshot=setup(db,test_user,test_library,monkeypatch)
    if problem=='replacement':event.manifest_proof['chapters'][0]['chapter_key']=str(uuid4())
    elif problem=='source':event.manifest_proof['source']={**snapshot.source,'story_id':999}
    elif problem=='fingerprint':event.manifest_proof['fingerprint']='f'*64
    else:
        async def caps(*args,**kwargs):return {'protocols':[1]}
        monkeypatch.setattr(metadata_client,'_manifest_request',caps)
    assert run(db,event)['state']=='review_required'
    assert db.query(Chapter).count()==0 and db.query(ChapterDownloadJob).count()==0
    assert db.query(NovelUpdateEvent).one().event_type=='source_manifest_review_required'
    assert run(db,event)['state']=='duplicate'


def test_late_and_legacy_wakeup_can_accept_independently_proven_newer_append(db,test_user,test_library,monkeypatch):
    novel,event,snapshot=setup(db,test_user,test_library,monkeypatch)
    event.manifest_proof['revision']='c'*64
    assert run(db,event)['queued_downloads']==3
    event.delivery_id=str(uuid4());event.manifest_proof=None
    assert run(db,event)['created_events']==0
    assert db.query(NovelUpdateEvent).count()==1 and db.query(Chapter).count()==3


def test_transient_manifest_failure_does_not_consume_receipt(db,test_user,test_library,monkeypatch):
    novel,event,snapshot=setup(db,test_user,test_library,monkeypatch)
    async def unavailable(*args,**kwargs):raise metadata_client.ChapterManifestError('manifest_unavailable','Retry later',retryable=True)
    monkeypatch.setattr(metadata_client,'get_chapter_manifest',unavailable)
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as error:run(db,event)
    assert error.value.status_code==503 and db.query(MetadataWebhookDelivery).count()==0


@pytest.mark.parametrize('change',['replacement','category'])
def test_same_ordinal_never_retargets_or_category_syncs_an_existing_chapter(db,test_user,test_library,monkeypatch,change):
    novel,event,snapshot=setup(db,test_user,test_library,monkeypatch)
    from app.services.chapter_manifest_service import ingest_metadata_snapshot
    ingest_metadata_snapshot(db,novel,snapshot);db.commit()
    chapter=db.query(Chapter).filter_by(novel_id=novel.id,chapter_number=7).one()
    original_key=chapter.chapter_key;chapter.content='Private retained original';db.commit()
    if change=='replacement':snapshot.items[-1]['chapter_key']=str(uuid4())
    else:snapshot.items[-1]['category']='author_note'
    event.manifest_proof=None
    result=run(db,event)
    assert result['state']=='review_required' and result['queued_downloads']==0
    db.refresh(chapter)
    assert chapter.chapter_key==original_key and chapter.category=='story' and chapter.content=='Private retained original'
    assert db.query(Chapter).count()==3


def test_immutable_keys_not_loaded_body_or_current_global_receipts_authorize_new_download(db,test_user,test_library,monkeypatch):
    novel,event,snapshot=setup(db,test_user,test_library,monkeypatch)
    assert run(db,event)['queued_downloads']==3
    for job in db.query(ChapterDownloadJob):
        assert job.chapter_identity['chapter_key'] and job.chapter_identity['manifest_epoch']
        assert job.chapter_identity['metadata_manifest_key']==snapshot.manifest_key



def test_chunk_group_consumes_fresh_manifest_once_but_receipts_every_delivery(db,test_user,test_library,monkeypatch):
    novel,event,snapshot=setup(db,test_user,test_library,monkeypatch)
    assert run(db,event)['created_events']==1
    async def forbidden(*args,**kwargs):raise AssertionError('A committed wake-up group must not refetch the whole manifest')
    monkeypatch.setattr(metadata_client,'_manifest_request',forbidden)
    monkeypatch.setattr(metadata_client,'get_chapter_manifest',forbidden)
    for index in range(3):
        event.delivery_id=str(uuid4());event.manifest_proof['chapters']=[]
        assert run(db,event)['state']=='duplicate_group'
    assert db.query(MetadataWebhookDelivery).count()==5  # four deliveries + one group
    assert db.query(NovelUpdateEvent).count()==1 and db.query(ChapterDownloadJob).count()==3



def test_actual_authenticated_route_awaits_guarded_ingestion_and_preserves_delivery_replay(client,db,test_user,test_library,monkeypatch):
    novel,event,snapshot=setup(db,test_user,test_library,monkeypatch)
    monkeypatch.setenv('NEXUS_NOVEL_WEBHOOK_SECRET','DISPOSABLE_WEBHOOK_FIXTURE')
    path='/novel/internal/metadata-events'
    assert client.post(path,json=vars(event)).status_code==401
    assert db.query(MetadataWebhookDelivery).count()==0;db.rollback()
    response=client.post(path,json=vars(event),headers={'X-Nexus-Webhook-Secret':'DISPOSABLE_WEBHOOK_FIXTURE'})
    assert response.status_code==200,response.text
    assert response.json()['queued_downloads']==3 and response.json()['created_events']==1
    duplicate=client.post(path,json=vars(event),headers={'X-Nexus-Webhook-Secret':'DISPOSABLE_WEBHOOK_FIXTURE'})
    assert duplicate.status_code==200 and duplicate.json()['state']=='duplicate'
    assert db.query(Chapter).count()==3 and db.query(ChapterDownloadJob).count()==3


@pytest.mark.parametrize('field',['new_chapter_numbers','chapters'])
def test_actual_route_rejects_oversized_chunks_without_manifest_rpc_or_receipt(client,db,test_user,test_library,monkeypatch,field):
    _,event,_=setup(db,test_user,test_library,monkeypatch)
    monkeypatch.setenv('NEXUS_NOVEL_WEBHOOK_SECRET','DISPOSABLE_WEBHOOK_FIXTURE')
    async def forbidden(*args,**kwargs):raise AssertionError('An oversized delivery must fail validation before remote work')
    monkeypatch.setattr(metadata_client,'_manifest_request',forbidden)
    payload=vars(event).copy();payload[field]=list(range(1001)) if field=='new_chapter_numbers' else [{'chapter_number':number} for number in range(1001)]
    response=client.post('/novel/internal/metadata-events',json=payload,headers={'X-Nexus-Webhook-Secret':'DISPOSABLE_WEBHOOK_FIXTURE'})
    assert response.status_code==422 and db.query(MetadataWebhookDelivery).count()==0


@pytest.mark.parametrize('change',['oversized','unknown','boolean_ordinal'])
def test_actual_route_rejects_invalid_proof_before_rpc_and_claim(client,db,test_user,test_library,monkeypatch,change):
    _,event,_=setup(db,test_user,test_library,monkeypatch)
    monkeypatch.setenv('NEXUS_NOVEL_WEBHOOK_SECRET','DISPOSABLE_WEBHOOK_FIXTURE')
    async def forbidden(*args,**kwargs):raise AssertionError('Invalid proof must not request source data')
    monkeypatch.setattr(metadata_client,'_manifest_request',forbidden)
    if change=='oversized':event.manifest_proof['chapters']*=1001
    elif change=='unknown':event.manifest_proof['override_identity']=True
    else:event.manifest_proof['chapters'][0]['chapter_number']=True
    response=client.post('/novel/internal/metadata-events',json=vars(event),headers={'X-Nexus-Webhook-Secret':'DISPOSABLE_WEBHOOK_FIXTURE'})
    assert response.status_code==422 and db.query(MetadataWebhookDelivery).count()==0


@pytest.mark.parametrize('change',['fingerprint','source'])
def test_mutated_header_cannot_borrow_committed_group_fast_path(db,test_user,test_library,monkeypatch,change):
    novel,event,snapshot=setup(db,test_user,test_library,monkeypatch)
    assert run(db,event)['created_events']==1
    event.delivery_id=str(uuid4())
    if change=='fingerprint':event.manifest_proof['fingerprint']='f'*64
    else:event.manifest_proof['source']={**snapshot.source,'story_id':999}
    calls=[]
    async def caps(*args,**kwargs):calls.append(1);return {'protocols':[1],'content_identity':True}
    monkeypatch.setattr(metadata_client,'_manifest_request',caps)
    assert run(db,event)['state']=='review_required' and calls==[1]
    assert db.query(Chapter).count()==3 and db.query(ChapterDownloadJob).count()==3
