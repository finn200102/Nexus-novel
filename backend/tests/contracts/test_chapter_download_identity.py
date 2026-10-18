"""Late source responses cannot publish into a different chapter lifecycle."""
# ruff: noqa: F811
from uuid import uuid4
import pytest
from sqlalchemy.orm import sessionmaker
from app.models import Chapter
from app.models.chapter import ContentStatus
from app.models.download_job import ChapterDownloadJob
from app.services import chapter_download_identity_service as service
from app.services.chapter_identity_service import source_version
from tests.routes.test_reader_tools import story
from tests.routes.conftest import db,test_user,test_library  # noqa: F401


@pytest.fixture
def bound(db,test_library):
    novel,chapter,_=story(db,test_library);novel.metadata_id=123
    chapter.metadata_manifest_key=str(uuid4());chapter.metadata_chapter_key=str(uuid4())
    chapter.content_status=ContentStatus.PROCESSING
    from app.models.chapter_manifest import ChapterManifestState
    db.flush();db.get(ChapterManifestState,novel.id).metadata_source={'site':'royalroad','story_id':123,'source_url':'https://www.royalroad.com/fiction/123'}
    db.commit()
    return novel,chapter


def test_job_insert_snapshots_owned_lifecycle_and_not_an_arbitrary_supplied_key(db,test_user,test_library,bound):
    novel,chapter=bound
    job=ChapterDownloadJob(user_id=test_user.id,library_id=test_library.id,novel_id=novel.id,chapter_id=chapter.id)
    db.add(job);db.commit()
    assert job.chapter_identity['chapter_key']==chapter.chapter_key and job.chapter_identity['metadata_chapter_key']==chapter.metadata_chapter_key
    bad=ChapterDownloadJob(user_id=test_user.id,library_id=test_library.id,novel_id=novel.id,chapter_id=chapter.id,status='completed',chapter_identity={'chapter_key':str(uuid4())})
    db.add(bad)
    with pytest.raises(ValueError):db.flush()
    db.rollback()


def test_metadata_key_change_prevents_every_late_publication(db,test_user,test_library,bound):
    novel,chapter=bound
    expected=service.capture(db,chapter,user_id=test_user.id,library_id=test_library.id);version=source_version(chapter)
    chapter.metadata_chapter_key=str(uuid4());db.commit()
    assert not service.publish(db,user_id=test_user.id,library_id=test_library.id,novel_id=novel.id,chapter_id=chapter.id,expected=expected,
        value={'content':'Wrong source must never replace original'},expected_source_version=version)
    db.refresh(chapter);assert chapter.content=='Alice arrives at the castle.\nBob welcomes Alice.'


def test_cancelled_download_late_response_is_discarded_without_cancelling_new_attempt(db,test_user,test_library,bound):
    novel,chapter=bound
    expected=service.capture(db,chapter,user_id=test_user.id,library_id=test_library.id);version=source_version(chapter)
    job=ChapterDownloadJob(user_id=test_user.id,library_id=test_library.id,novel_id=novel.id,chapter_id=chapter.id,status='processing',lease_owner='reused-owner',attempt_count=1)
    db.add(job);db.commit();job.attempt_count=2;db.commit()
    assert not service.publish(db,user_id=test_user.id,library_id=test_library.id,novel_id=novel.id,chapter_id=chapter.id,expected=expected,
        job_id=job.id,lease_owner='reused-owner',attempt=1,value={'content':'Old callback'},expected_source_version=version)
    db.refresh(job);assert job.status=='processing' and job.attempt_count==2


def test_real_worker_uses_bound_remote_keys_and_drops_late_archived_response(db,test_user,test_library,bound,monkeypatch):
    from app.routers.chapter import download_chapter_background
    novel,chapter=bound;key=chapter.chapter_key;chapter_id=chapter.id
    expected=service.capture(db,chapter,user_id=test_user.id,library_id=test_library.id)
    factory=sessionmaker(bind=db.get_bind())
    calls=[]
    def fetch(metadata_id,number,**kwargs):
        calls.append(kwargs)
        with factory() as other:
            current=other.query(Chapter).filter_by(id=chapter_id).one();current.archived=True;other.commit()
        return {'text':'Late source response','manifest_key':expected['metadata_manifest_key'],'chapter_key':expected['metadata_chapter_key']}
    monkeypatch.setattr('app.services.metadata_client.fetch_public_chapter_text_sync',fetch)
    download_chapter_background(chapter_id,novel.id,chapter.chapter_number,test_library.id,factory,expected_identity=expected,expected_user_id=test_user.id)
    assert calls==[{'expected_manifest_key':expected['metadata_manifest_key'],'expected_chapter_key':expected['metadata_chapter_key'],'expected_source':expected['metadata_source']}]
    db.expire_all();original=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(chapter_key=key).one()
    assert original.archived and 'Late source' not in original.content


def test_unbound_task_and_legacy_callback_never_dispatch_source(db,test_user,test_library,bound,monkeypatch):
    from app.routers.chapter import download_chapter_background
    novel,chapter=bound
    def never(*args,**kwargs):raise AssertionError('An unbound callback must not fetch a source')
    monkeypatch.setattr('app.services.metadata_client.fetch_public_chapter_text_sync',never)
    download_chapter_background(chapter.id,novel.id,chapter.chapter_number,test_library.id,sessionmaker(bind=db.get_bind()))
    db.refresh(chapter);assert chapter.content_status==ContentStatus.PROCESSING


def test_legacy_queued_job_without_proof_fails_before_source_io(db,test_user,test_library,bound,monkeypatch):
    from sqlalchemy import update
    from app.routers.chapter import run_queued_download
    novel,chapter=bound;chapter.content_status=ContentStatus.MISSING
    job=ChapterDownloadJob(user_id=test_user.id,library_id=test_library.id,novel_id=novel.id,chapter_id=chapter.id)
    db.add(job);db.commit()
    # Simulate0053 upgrade: existing jobs remain explicitly unknown.
    db.execute(update(ChapterDownloadJob).where(ChapterDownloadJob.id==job.id).values(chapter_identity=None));db.commit()
    def never(*args,**kwargs):raise AssertionError('Unknown legacy jobs cannot dispatch a source')
    monkeypatch.setattr('app.services.metadata_client.fetch_public_chapter_text_sync',never)
    run_queued_download(job.id,sessionmaker(bind=db.get_bind()))
    db.expire_all();assert job.status=='failed' and job.error_code=='CHAPTER_REVIEW_REQUIRED'


def test_cancel_of_old_job_cannot_reset_processing_replacement_at_reused_pk(db,test_user,test_library,bound):
    from sqlalchemy import delete
    from app.services.download_job_service import cancel_job
    novel,chapter=bound;chapter_id=chapter.id
    job=ChapterDownloadJob(user_id=test_user.id,library_id=test_library.id,novel_id=novel.id,chapter_id=chapter_id)
    db.add(job);db.commit();old_key=job.chapter_identity['chapter_key']
    db.execute(delete(Chapter).where(Chapter.id==chapter_id));db.commit();db.expunge(chapter)
    replacement=Chapter(id=chapter_id,novel_id=novel.id,chapter_number=1,content='Replacement private text',content_status=ContentStatus.PROCESSING,
        metadata_manifest_key=str(uuid4()),metadata_chapter_key=str(uuid4()))
    db.add(replacement);db.commit()
    assert replacement.chapter_key!=old_key
    cancel_job(db,job)
    db.refresh(replacement);assert replacement.content_status==ContentStatus.PROCESSING
    db.refresh(job);assert job.status=='cancelled'


def test_retry_never_adopts_a_changed_binding_or_stale_loaded_job(db,test_user,test_library,bound):
    from fastapi import HTTPException
    from app.services.download_job_service import retry_job
    novel,chapter=bound
    job=ChapterDownloadJob(user_id=test_user.id,library_id=test_library.id,novel_id=novel.id,chapter_id=chapter.id,status='failed',attempt_count=3)
    db.add(job);db.commit()
    with sessionmaker(bind=db.get_bind())() as other:
        fresh=other.get(ChapterDownloadJob,job.id);fresh.status='processing';fresh.lease_owner='new-attempt';other.commit()
    with pytest.raises(HTTPException) as caught:retry_job(db,job)
    assert caught.value.status_code==409
    db.rollback();db.refresh(job);assert job.status=='processing' and job.lease_owner=='new-attempt'
    job.status='failed';chapter.metadata_chapter_key=str(uuid4());db.commit()
    with pytest.raises(HTTPException) as caught:retry_job(db,job)
    assert caught.value.detail['code']=='chapter_review_required'
    db.rollback();db.refresh(job);assert job.status=='failed' and job.attempt_count==3
