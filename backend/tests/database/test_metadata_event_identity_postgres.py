"""Actual concurrent event/manual-sync publication uses account serialization."""
# ruff: noqa: F811
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Barrier,Lock
from uuid import uuid4
import pytest
from sqlalchemy.orm import sessionmaker
from app.models import User,Library,Novel,Chapter
from app.models.download_job import ChapterDownloadJob
from app.models.update_event import NovelUpdateEvent
from app.models.metadata_webhook_delivery import MetadataWebhookDelivery
from app.services import metadata_event_ingestion as service,metadata_client
from app.services.chapter_manifest_service import ingest_metadata_snapshot
from config.database import Base
from tests.database.test_reading_run_migration import run_engine  # noqa: F401
from tests.routes.test_metadata_event_identity import setup


@pytest.mark.parametrize('same_delivery',[True,False])
def test_postgres_concurrent_events_publish_append_and_notification_once(run_engine,monkeypatch,same_delivery):
    if run_engine.dialect.name!='postgresql':pytest.skip('Requires real row-lock serialization')
    Base.metadata.create_all(run_engine);sessions=sessionmaker(bind=run_engine)
    with sessions() as db:
        user=User(username='event-owner',password='unused');db.add(user);db.flush()
        library=Library(name='Owned',user_id=user.id);db.add(library);db.commit()
        novel,event,snapshot=setup(db,user,library,monkeypatch);novel_id=novel.id
    barrier=Barrier(2)
    async def manifest(*args,**kwargs):barrier.wait(timeout=10);return deepcopy(snapshot)
    monkeypatch.setattr(metadata_client,'get_chapter_manifest',manifest)
    events=[deepcopy(event),deepcopy(event)]
    if not same_delivery:
        events[1].delivery_id=str(uuid4())
        events[1].manifest_proof['chapters']=[dict(chapter_key=snapshot.items[0]['chapter_key'],chapter_number=-2)]
    def deliver(value):
        with sessions() as db:return asyncio.run(service.receive_completed(db,value))
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(deliver,events))
    assert sum(result['created_events'] for result in results)==1
    assert sum(result['queued_downloads'] for result in results)==3
    with sessions() as db:
        assert db.query(Chapter).filter_by(novel_id=novel_id).count()==3
        assert db.query(ChapterDownloadJob).count()==3 and db.query(NovelUpdateEvent).count()==1
        assert db.query(MetadataWebhookDelivery).count()==(2 if same_delivery else 3)


@pytest.mark.parametrize('change',['manual_sync','source_changed','account_disabled'])
def test_publication_rechecks_source_after_remote_manifest_wait(run_engine,monkeypatch,change):
    Base.metadata.create_all(run_engine);sessions=sessionmaker(bind=run_engine)
    with sessions() as db:
        user=User(username='event-owner',password='unused');db.add(user);db.flush()
        library=Library(name='Owned',user_id=user.id);db.add(library);db.commit()
        novel,event,snapshot=setup(db,user,library,monkeypatch);novel_id,user_id=novel.id,user.id
    async def manifest(*args,**kwargs):
        with sessions() as other:
            novel=other.get(Novel,novel_id)
            if change=='manual_sync':ingest_metadata_snapshot(other,novel,snapshot)
            elif change=='source_changed':novel.source_url='https://www.royalroad.com/fiction/999'
            else:other.get(User,user_id).is_disabled=True
            other.commit()
        return deepcopy(snapshot)
    monkeypatch.setattr(metadata_client,'get_chapter_manifest',manifest)
    with sessions() as db:result=asyncio.run(service.receive_completed(db,event))
    assert result['created_events']==0 and result['queued_downloads']==0
    with sessions() as db:
        assert db.query(Chapter).count()==(3 if change=='manual_sync' else 0)
        assert db.query(ChapterDownloadJob).count()==0 and db.query(NovelUpdateEvent).count()==0



def test_postgres_first_chunk_transient_failure_is_retryable_after_other_chunk_commits(run_engine,monkeypatch):
    if run_engine.dialect.name!='postgresql':pytest.skip('Requires real row-lock serialization')
    from fastapi import HTTPException
    Base.metadata.create_all(run_engine);sessions=sessionmaker(bind=run_engine)
    with sessions() as db:
        user=User(username='event-owner',password='unused');db.add(user);db.flush()
        library=Library(name='Owned',user_id=user.id);db.add(library);db.commit()
        _,event,snapshot=setup(db,user,library,monkeypatch)
    barrier=Barrier(2);counter=Lock();calls=[]
    async def manifest(*args,**kwargs):
        with counter:index=len(calls);calls.append(index)
        barrier.wait(timeout=10)
        if index==0:raise metadata_client.ChapterManifestError('manifest_unavailable','Temporary fixture failure',retryable=True)
        return deepcopy(snapshot)
    monkeypatch.setattr(metadata_client,'get_chapter_manifest',manifest)
    events=[deepcopy(event),deepcopy(event)];events[1].delivery_id=str(uuid4())
    def deliver(value):
        with sessions() as db:
            try:return asyncio.run(service.receive_completed(db,value))
            except HTTPException as exc:return {'status':exc.status_code,'delivery':value}
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(deliver,events))
    failed=next(result['delivery'] for result in results if result.get('status')==503)
    assert sum(result.get('created_events',0) for result in results)==1 and len(calls)==2
    assert deliver(failed)['state']=='duplicate_group' and len(calls)==2
    with sessions() as db:
        assert db.query(Chapter).count()==3 and db.query(ChapterDownloadJob).count()==3
        assert db.query(NovelUpdateEvent).count()==1 and db.query(MetadataWebhookDelivery).count()==3



def test_newer_remote_append_is_not_lost_when_manual_sync_publishes_an_older_snapshot_during_wait(run_engine,monkeypatch):
    Base.metadata.create_all(run_engine);sessions=sessionmaker(bind=run_engine)
    with sessions() as db:
        user=User(username='event-owner',password='unused');db.add(user);db.flush()
        library=Library(name='Owned',user_id=user.id);db.add(library);db.commit()
        novel,event,old=setup(db,user,library,monkeypatch);novel_id=novel.id
    from dataclasses import replace
    latest=replace(old,revision='c'*64,fingerprint='d'*64,total=4,items=deepcopy(old.items))
    latest.items.append({**latest.items[-1],'id':80,'chapter_key':str(uuid4()),'chapter_id':180,'chapter_number':9,'title':'Newest','url':'https://www.royalroad.com/fiction/18/chapter/180'})
    async def manifest(*args,**kwargs):
        with sessions() as other:
            ingest_metadata_snapshot(other,other.get(Novel,novel_id),old);other.commit()
        return latest
    monkeypatch.setattr(metadata_client,'get_chapter_manifest',manifest)
    with sessions() as db:result=asyncio.run(service.receive_completed(db,event))
    assert result['created_events']==1 and result['queued_downloads']==1
    with sessions() as db:
        assert db.query(Chapter).count()==4
        notice=db.query(NovelUpdateEvent).one();assert notice.details['chapter_numbers']==[9]
        assert db.query(ChapterDownloadJob).one().chapter_identity['metadata_chapter_key']==latest.items[-1]['chapter_key']


@pytest.mark.parametrize('change',['namespace','source_header'])
def test_known_manifest_binding_cannot_be_replaced_under_webhook_advance_exception(run_engine,monkeypatch,change):
    from dataclasses import replace
    from app.models.chapter_manifest import ChapterManifestState
    Base.metadata.create_all(run_engine);sessions=sessionmaker(bind=run_engine)
    with sessions() as db:
        user=User(username='event-owner',password='unused');db.add(user);db.flush()
        library=Library(name='Owned',user_id=user.id);db.add(library);db.commit()
        novel,event,old=setup(db,user,library,monkeypatch);novel_id=novel.id
        ingest_metadata_snapshot(db,novel,old);db.commit()
    latest=replace(old,revision='c'*64,fingerprint='d'*64,total=4,items=deepcopy(old.items))
    latest.items.append({**latest.items[-1],'id':80,'chapter_key':str(uuid4()),'chapter_id':180,'chapter_number':9,'title':'Newest','url':'https://www.royalroad.com/fiction/18/chapter/180'})
    async def manifest(*args,**kwargs):
        with sessions() as other:
            state=other.get(ChapterManifestState,novel_id)
            if change=='namespace':state.metadata_manifest_key=str(uuid4())
            else:state.metadata_source={**old.source,'story_id':999}
            other.commit()
        return latest
    monkeypatch.setattr(metadata_client,'get_chapter_manifest',manifest)
    with sessions() as db:result=asyncio.run(service.receive_completed(db,event))
    assert result['state']=='source_changed' and result['created_events']==0
    with sessions() as db:
        assert db.query(Chapter).count()==3 and db.query(ChapterDownloadJob).count()==0
        assert db.query(NovelUpdateEvent).count()==0 and db.query(MetadataWebhookDelivery).count()==1
