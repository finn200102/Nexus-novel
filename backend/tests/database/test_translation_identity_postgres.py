"""Identity/account-lock fences use real PostgreSQL and isolated schemas."""
# ruff: noqa: F811
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from decimal import Decimal
from threading import Barrier
import pytest
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker
from app.models import User,Library,Novel,Chapter
from app.models.chapter import ContentStatus
from app.models.translation import ReaderProvider,TranslationJob,ReaderProviderRequest
from app.models.story_processing_permission import StoryProcessingPermission
from app.services import translation_service as service
from app.services.chapter_document import from_text
from app.services.chapter_identity_service import identity
from app.services.notification_crypto import encrypt_url
from tests.database.test_reading_run_migration import run_engine  # noqa: F401
from config.database import Base


def seed(engine,monkeypatch,*,paid=False):
    Base.metadata.create_all(engine);sessions=sessionmaker(bind=engine)
    monkeypatch.setenv('NEXUS_LOCAL_AI_BASE_URL','http://translation.invalid/v1')
    monkeypatch.setattr(service,'heartbeat',lambda *args:nullcontext())
    with sessions() as db:
        user=User(username='translation-proof',password='unused');db.add(user);db.flush()
        library=Library(user_id=user.id,name='Private');db.add(library);db.flush()
        novel=Novel(title='Signed original',library_id=library.id);db.add(novel);db.flush()
        doc=from_text('Alice sees the sea.')
        chapter=Chapter(novel_id=novel.id,chapter_number=-2,title='Prologue',content=doc['plain_text'],document=doc,content_status=ContentStatus.PRESENT)
        provider=ReaderProvider(user_id=user.id,name='Fixture',kind='openai_compatible' if paid else 'local',
            base_url='https://example.invalid/v1' if paid else 'http://translation.invalid/v1',model='fixture',
            secret_ciphertext=encrypt_url('DISPOSABLE_TEST_KEY') if paid else None,input_price=Decimal('1'),output_price=Decimal('2'),budget_microusd=1_000_000)
        db.add_all([chapter,provider]);db.flush()
        db.add(StoryProcessingPermission(user_id=user.id,novel_id=novel.id,provider_id=provider.id,translation=True))
        db.commit();db.refresh(chapter)
        proof={**{f'expected_{key}':value for key,value in identity(chapter).items()},'expected_content_version':doc['content_version']}
        ids=(user.id,novel.id,chapter.id,provider.id)
    return sessions,ids,proof


def queue(db,ids,proof):
    user,novel,chapter,provider=ids
    return service.queue_translation(db,db.get(User,user),db.get(Novel,novel),db.get(Chapter,chapter),db.get(ReaderProvider,provider),'de',identity_expectations=proof)


def test_same_reviewed_identity_concurrently_creates_one_variant(run_engine,monkeypatch):
    if run_engine.dialect.name!='postgresql':pytest.skip('Actual PostgreSQL row-lock concurrency')
    sessions,ids,proof=seed(run_engine,monkeypatch);barrier=Barrier(2)
    def submit(_):
        with sessions() as db:
            barrier.wait(timeout=10)
            return queue(db,ids,proof).id
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(submit,range(2)))
    assert results[0]==results[1]
    with sessions() as db:assert db.query(TranslationJob).count()==1


@pytest.mark.parametrize('change',['archive','cancel_retry'])
def test_paid_response_after_identity_or_attempt_change_is_charged_once_but_not_published(run_engine,monkeypatch,change):
    sessions,ids,proof=seed(run_engine,monkeypatch,paid=True)
    with sessions() as db:job_id=queue(db,ids,proof).id
    calls=[]
    def response(*args,**kwargs):
        calls.append(kwargs['prompt'])
        with sessions() as other:
            if change=='archive':other.get(Chapter,ids[2]).archived=True
            else:
                job=other.get(TranslationJob,job_id);job.status='queued';job.attempt_count=0;job.lease_owner=None;job.lease_expires_at=None
            other.commit()
        return {'choices':[{'message':{'content':'Alice sieht das Meer.'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':10,'completion_tokens':5}}
    monkeypatch.setattr('app.services.reader_provider.direct_request',response)
    service.process_translation(job_id,sessions)
    with sessions() as db:
        job=db.get(TranslationJob,job_id)
        assert job.status==('failed' if change=='archive' else 'queued') and job.translated_blocks==[]
        provider=db.get(ReaderProvider,ids[3]);assert provider.used_microusd==20 and provider.reserved_microusd==0
        assert db.query(ReaderProviderRequest).count()==1
        assert service.job_view(job)['charged_usd']==.00002
    if change=='cancel_retry':
        # A recovered paragraph with a completed ledger receipt cannot resend.
        service.process_translation(job_id,sessions)
        with sessions() as db:
            job=db.get(TranslationJob,job_id)
            assert job.status=='failed' and job.error_code=='PAID_REQUEST_UNRESOLVED'
        assert len(calls)==1


def test_unrelated_manifest_append_allows_accepted_job_but_rejects_stale_new_queue(run_engine,monkeypatch):
    sessions,ids,proof=seed(run_engine,monkeypatch)
    with sessions() as db:
        job_id=queue(db,ids,proof).id
        db.add(Chapter(novel_id=ids[1],chapter_number=99,title='Later append'));db.commit()
        with pytest.raises(HTTPException) as error:queue(db,ids,proof)
        assert error.value.detail['code']=='chapter_manifest_changed'
    monkeypatch.setattr('app.services.reader_provider.direct_request',lambda *a,**kw:{'choices':[{'message':{'content':'Übersetzt.'},'finish_reason':'stop'}]})
    service.process_translation(job_id,sessions)
    with sessions() as db:assert db.get(TranslationJob,job_id).status=='completed'


@pytest.mark.parametrize('action',['cancel','retry'])
def test_action_refreshes_preloaded_stale_job_before_mutating_newer_attempt(run_engine,monkeypatch,action):
    from app.routers.reader_tools import translation_action,JobAction
    from app.services.job_lease import claim
    sessions,ids,proof=seed(run_engine,monkeypatch)
    with sessions() as db:job_id=queue(db,ids,proof).id
    with sessions() as stale:
        old=stale.get(TranslationJob,job_id)
        if action=='retry':old.status='failed';stale.commit();stale.refresh(old)
        stale.get(User,ids[0]);stale.rollback()
        # Keep the old status in the identity map while another session wins.
        old=stale.get(TranslationJob,job_id)
        with sessions() as other:
            newer=other.get(TranslationJob,job_id)
            if action=='cancel':
                newer.status='completed';newer.translated_blocks=newer.source_blocks;other.commit()
                expected='completed';owner=None
            else:
                newer.status='queued';other.commit();claimed=claim(other,TranslationJob,job_id)
                expected='processing';owner=claimed.lease_owner
        result=translation_action(job_id,JobAction(action=action),stale,stale.get(User,ids[0]))
        assert result['status']==expected
    with sessions() as db:
        job=db.get(TranslationJob,job_id)
        assert job.status==expected
        if action=='retry':assert job.lease_owner==owner and job.attempt_count==1
