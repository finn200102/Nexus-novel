"""Real PostgreSQL row-lock and publication races; SQLite compatibility too."""
# ruff: noqa: F811
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from threading import Barrier
import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker
from app.models import User, Library, Novel, Chapter, ChapterAudioJob
from app.models.chapter import ContentStatus
from app.services import audio_job_service as audio
from app.services.chapter_document import from_text
from app.services.chapter_identity_service import identity
from tests.database.test_reading_run_migration import run_engine  # noqa: F401
from tests.routes.test_audio_alignment import audio as wav
from config.database import Base

PROVIDER={'id':'custom','base_url':'http://audio.invalid/v1','model':'fixture','voice':'fixture'}


def seed(engine,monkeypatch,tmp_path):
    Base.metadata.create_all(engine)
    sessions=sessionmaker(bind=engine)
    with sessions() as db:
        user=User(username='audio-identity',password='unused');db.add(user);db.flush()
        library=Library(user_id=user.id,name='Private');db.add(library);db.flush()
        novel=Novel(library_id=library.id,title='Signed chapters');db.add(novel);db.flush()
        document=from_text('Exact original words.')
        chapter=Chapter(novel_id=novel.id,chapter_number=0,title='Zero',document=document,content=document['plain_text'],content_status=ContentStatus.PRESENT)
        db.add(chapter);db.commit();db.refresh(chapter)
        proof={f'expected_{key}':value for key,value in identity(chapter).items()}
        proof['expected_content_version']=document['content_version']
        ids=dict(user_id=user.id,library_id=library.id,novel_id=novel.id)
        chapter_id=chapter.id
    monkeypatch.setenv('DOWNLOAD_PATH',str(tmp_path))
    monkeypatch.setattr(audio,'heartbeat',lambda *args:nullcontext())
    return sessions,ids,chapter_id,proof


def enqueue(db,ids,chapter_id,proof):
    return audio.queue_audio_job(db,**ids,chapter=db.get(Chapter,chapter_id),provider=PROVIDER,identity_expectations=proof)


def test_accepted_identity_keeps_original_revision_but_new_queue_requires_current(run_engine,monkeypatch,tmp_path):
    sessions,ids,chapter_id,proof=seed(run_engine,monkeypatch,tmp_path)
    with sessions() as db:
        job=enqueue(db,ids,chapter_id,proof);job_id=job.id
        db.add(Chapter(novel_id=ids['novel_id'],chapter_number=700,title='Unrelated append'));db.commit()
        with pytest.raises(HTTPException) as error:enqueue(db,ids,chapter_id,proof)
        assert error.value.detail['code']=='chapter_manifest_changed'
    calls=[]
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            calls.append(url)
            return httpx.Response(200,request=httpx.Request('POST',url),content=wav(.1))
    monkeypatch.setattr(audio.httpx,'Client',Client)
    audio.process_audio_job(job_id,sessions)
    with sessions() as db:
        job=db.get(ChapterAudioJob,job_id)
        assert calls and job.status=='completed' and job.manifest_revision==proof['expected_manifest_revision']
        assert job.chapter_key==proof['expected_chapter_key'] and not job.identity_inferred


def test_concurrent_exact_queue_serializes_to_one_owned_job(run_engine,monkeypatch,tmp_path):
    if run_engine.dialect.name!='postgresql':pytest.skip('Actual PostgreSQL account row lock')
    sessions,ids,chapter_id,proof=seed(run_engine,monkeypatch,tmp_path)
    barrier=Barrier(2)
    def create(_):
        with sessions() as db:
            barrier.wait(timeout=10)
            return enqueue(db,ids,chapter_id,proof).id
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(create,range(2)))
    assert results[0]==results[1]
    with sessions() as db:assert db.query(ChapterAudioJob).count()==1


@pytest.mark.parametrize('change',['archive','cancel_retry'])
def test_original_provider_reply_cannot_publish_after_authority_change(run_engine,monkeypatch,tmp_path,change):
    sessions,ids,chapter_id,proof=seed(run_engine,monkeypatch,tmp_path)
    with sessions() as db:job_id=enqueue(db,ids,chapter_id,proof).id
    calls=[]
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            calls.append(url)
            if len(calls)==1:
                with sessions() as other:
                    if change=='archive':
                        chapter=other.get(Chapter,chapter_id);chapter.archived=True
                    else:
                        # Exact cancel/retry ABA while old provider request is in flight.
                        job=other.get(ChapterAudioJob,job_id);job.status='queued';job.lease_owner=None
                        job.lease_expires_at=None;job.attempt_count=0
                    other.commit()
            return httpx.Response(200,request=httpx.Request('POST',url),content=wav(.1))
    monkeypatch.setattr(audio.httpx,'Client',Client)
    audio.process_audio_job(job_id,sessions)
    with sessions() as db:
        job=db.get(ChapterAudioJob,job_id)
        assert job.status==('failed' if change=='archive' else 'queued')
        assert not job.audio_path and not list(tmp_path.rglob('*.wav'))
    if change=='cancel_retry':
        audio.process_audio_job(job_id,sessions)
        with sessions() as db:assert db.get(ChapterAudioJob,job_id).status=='completed'


def test_owned_export_and_feed_keep_captured_identity_and_filter_archive(run_engine,monkeypatch,tmp_path):
    from app.services import audio_export_service as exports, podcast_audio_service as podcasts, podcast_service
    sessions,ids,chapter_id,proof=seed(run_engine,monkeypatch,tmp_path)
    with sessions() as db:
        job=enqueue(db,ids,chapter_id,proof);job_id=job.id
        path=tmp_path/'audio'/str(ids['user_id'])/str(job_id)/'chapter.wav'
        path.parent.mkdir(parents=True);path.write_bytes(wav(.1))
        job.status='completed';job.audio_path=str(path);db.commit()
        queued=exports.queue_export(db,user_id=ids['user_id'],novel_id=ids['novel_id'],audio_job_ids=[job_id])
        assert queued.chapters[0]['chapter_key']==proof['expected_chapter_key']
        podcast_service.rotate(db,ids['user_id'],ids['novel_id'])
        assert podcasts.discover(db,user_id=ids['user_id'],novel_id=ids['novel_id'])==1
        assert podcasts.status(db,ids['user_id'],ids['novel_id'])['episodes_total']==1
        chapter=db.get(Chapter,chapter_id);chapter.archived=True;db.commit()
        assert podcasts.status(db,ids['user_id'],ids['novel_id'])['episodes_total']==0
        # Explicit immutable recording selection remains exportable in archive.
        archived=exports.queue_export(db,user_id=ids['user_id'],novel_id=ids['novel_id'],audio_job_ids=[job_id])
        assert archived.chapters[0]['chapter_archived']
