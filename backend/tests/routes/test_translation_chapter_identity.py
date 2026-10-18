"""Private saved variants retain originals without numeric-address authority."""
from contextlib import nullcontext
from uuid import uuid4
from io import BytesIO
from zipfile import ZipFile
import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.models import Chapter,Novel
from app.models.chapter import ContentStatus
from app.models.translation import ReaderProvider,TranslationJob,ReaderProviderRequest
from app.services import translation_service as service
from app.services.chapter_document import from_text
from app.services.chapter_identity_service import identity


def setup(db,user,library,monkeypatch):
    monkeypatch.setenv('NEXUS_LOCAL_AI_BASE_URL','http://translation.invalid/v1')
    novel=Novel(title='Original translations',library_id=library.id);db.add(novel);db.flush()
    doc=from_text('Alice sees the sea.')
    chapter=Chapter(novel_id=novel.id,chapter_number=0,title='Original prologue',document=doc,content=doc['plain_text'],content_status=ContentStatus.PRESENT)
    provider=ReaderProvider(user_id=user.id,name='Local',kind='local',base_url='http://translation.invalid/v1',model='fixture')
    db.add_all([chapter,provider]);db.commit();db.refresh(chapter)
    monkeypatch.setattr(service,'heartbeat',lambda *args:nullcontext())
    return novel,chapter,provider


def proof(chapter):
    return {**{f'expected_{key}':value for key,value in identity(chapter).items()},'expected_content_version':chapter.document['content_version']}


def queue(client,headers,novel,chapter,provider,capture):
    return client.post(f'/reader/translations/{novel.id}/{chapter.chapter_number}',headers=headers,
        json={'provider_id':provider.id,'language':'de',**capture})


def mock(monkeypatch,calls,callback=None):
    def respond(*args,**kwargs):
        calls.append(kwargs['prompt'])
        if callback:callback()
        return {'choices':[{'message':{'content':'Alice sieht das Meer.'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':8,'completion_tokens':5}}
    monkeypatch.setattr('app.services.reader_provider.direct_request',respond)


def test_signed_single_queue_new_revision_rejected_but_accepted_original_continues(client,auth_headers,db,test_user,test_library,monkeypatch):
    novel,chapter,provider=setup(db,test_user,test_library,monkeypatch);capture=proof(chapter)
    result=queue(client,auth_headers,novel,chapter,provider,capture);assert result.status_code==202,result.text
    job_id=result.json()['id']
    db.add(Chapter(novel_id=novel.id,chapter_number=700,title='Later'));db.commit()
    stale=queue(client,auth_headers,novel,chapter,provider,capture)
    assert stale.status_code==409 and stale.json()['detail']['code']=='chapter_manifest_changed'
    db.rollback();calls=[];mock(monkeypatch,calls)
    service.process_translation(job_id,sessionmaker(bind=db.get_bind()));db.expire_all()
    job=db.get(TranslationJob,job_id)
    assert job.status=='completed' and len(calls)==1 and job.manifest_revision==capture['expected_manifest_revision']
    view=service.job_view(job)
    assert view['chapter_number']==0 and view['chapter_key']==capture['expected_chapter_key']
    assert view['source_version']==capture['expected_content_version'] and view['current_content_version']==job.source_version


@pytest.mark.parametrize('change',['archive','text','inferred'])
def test_pending_unproven_or_revised_original_never_dispatches(client,auth_headers,db,test_user,test_library,monkeypatch,change):
    novel,chapter,provider=setup(db,test_user,test_library,monkeypatch)
    job_id=queue(client,auth_headers,novel,chapter,provider,proof(chapter)).json()['id']
    if change=='archive':chapter.archived=True
    elif change=='text':chapter.document=from_text('Different original.')
    else:db.get(TranslationJob,job_id).identity_inferred=True
    db.commit();calls=[];mock(monkeypatch,calls)
    service.process_translation(job_id,sessionmaker(bind=db.get_bind()));db.expire_all()
    job=db.get(TranslationJob,job_id)
    assert not calls and job.status=='failed' and job.error_code=='translation_identity_review_required'
    assert client.post(f'/reader/translation-jobs/{job_id}',headers=auth_headers,json={'action':'retry'}).status_code==409


def test_equal_text_pk_reuse_never_attaches_completed_variant_and_saved_export_survives(client,auth_headers,db,test_user,test_library,monkeypatch):
    novel,chapter,provider=setup(db,test_user,test_library,monkeypatch);capture=proof(chapter)
    job_id=queue(client,auth_headers,novel,chapter,provider,capture).json()['id']
    calls=[];mock(monkeypatch,calls);service.process_translation(job_id,sessionmaker(bind=db.get_bind()));db.expire_all()
    chapter=db.get(Chapter,chapter.id);pk,doc=chapter.id,chapter.document
    db.execute(text('DELETE FROM chapters WHERE id=:id'),{'id':pk});db.commit();db.expunge(chapter)
    replacement=Chapter(id=pk,novel_id=novel.id,chapter_number=0,title='WRONG REPLACEMENT TITLE',document=doc,content=doc['plain_text'])
    db.add(replacement);db.commit()
    stale=queue(client,auth_headers,novel,replacement,provider,capture)
    assert stale.status_code==409
    result=client.get(f'/reader/translations/{novel.id}/0',headers=auth_headers).json()
    assert result==[]
    item=client.get(f'/reader/stories/{novel.id}/translations',headers=auth_headers).json()['items'][0]
    assert item['chapter_key'] is None and item['chapter_number'] is None and item['exportable']
    assert item['source_chapter_key']==capture['expected_chapter_key']
    exported=client.post(f'/reader/stories/{novel.id}/translations/epub',headers=auth_headers,json={'translation_job_ids':[job_id]})
    assert exported.status_code==200
    with ZipFile(BytesIO(exported.content)) as book:
        body=book.read('OEBPS/chapter-1.xhtml')
        assert b'Alice sieht das Meer.' in body and b'Original prologue' in body and b'WRONG REPLACEMENT' not in body


def test_response_after_archival_is_discarded_without_losing_private_original(client,auth_headers,db,test_user,test_library,monkeypatch):
    novel,chapter,provider=setup(db,test_user,test_library,monkeypatch)
    job_id=queue(client,auth_headers,novel,chapter,provider,proof(chapter)).json()['id']
    def archive():
        with sessionmaker(bind=db.get_bind())() as other:
            row=other.get(Chapter,chapter.id);row.archived=True;other.commit()
    calls=[];mock(monkeypatch,calls,archive)
    service.process_translation(job_id,sessionmaker(bind=db.get_bind()));db.expire_all()
    job=db.get(TranslationJob,job_id)
    assert len(calls)==1 and job.status=='failed' and not job.translated_blocks
    assert job.source_blocks[0]['text']=='Alice sees the sea.'


def test_batch_exact_id_coverage_and_stale_selected_snapshot(client,auth_headers,db,test_user,test_library,monkeypatch):
    novel,chapter,provider=setup(db,test_user,test_library,monkeypatch)
    body={'chapter_ids':[chapter.id],'provider_id':provider.id,'language':'de',
        'chapter_identities':[{'chapter_id':chapter.id,**proof(chapter)}]}
    endpoint=f'/reader/stories/{novel.id}/translation-batch/preview'
    for entries in ([],body['chapter_identities']*2,[{**body['chapter_identities'][0],'chapter_id':999}]):
        assert client.post(endpoint,headers=auth_headers,json={**body,'chapter_identities':entries}).status_code==422
    assert client.post(endpoint,headers=auth_headers,json=body).status_code==200
    db.add(Chapter(novel_id=novel.id,chapter_number=-2,title='Earlier'));db.commit()
    assert client.post(endpoint,headers=auth_headers,json=body).status_code==409
    assert db.query(TranslationJob).count()==0


def test_exact_migrated_completed_reuse_never_mutates_old_proof_or_bypasses_pending_charge(client,auth_headers,db,test_user,test_library,monkeypatch):
    novel,chapter,provider=setup(db,test_user,test_library,monkeypatch);capture=proof(chapter)
    job_id=queue(client,auth_headers,novel,chapter,provider,capture).json()['id']
    calls=[];mock(monkeypatch,calls);service.process_translation(job_id,sessionmaker(bind=db.get_bind()));db.expire_all()
    job=db.get(TranslationJob,job_id);job.identity_inferred=True;job.fingerprint='old-migrated-fingerprint';db.commit()
    repeated=queue(client,auth_headers,novel,chapter,provider,capture)
    assert repeated.status_code==202 and repeated.json()['id']==job_id
    assert db.get(TranslationJob,job_id).fingerprint=='old-migrated-fingerprint' and len(calls)==1
    job.status='queued';db.commit()
    blocked=queue(client,auth_headers,novel,chapter,provider,capture)
    assert blocked.status_code==409 and db.query(TranslationJob).count()==1
    job.status='failed'
    db.add(ReaderProviderRequest(request_key=str(uuid4()),user_id=test_user.id,provider_id=provider.id,
        translation_job_id=job_id,model_snapshot={},status='unknown',reserved_microusd=17));db.commit()
    blocked=queue(client,auth_headers,novel,chapter,provider,capture)
    assert blocked.status_code==409 and blocked.json()['detail']['code']=='paid_request_unresolved'
    assert db.query(TranslationJob).count()==1


@pytest.mark.parametrize('change',['stale_before','archive_after','append_after'])
def test_passage_identity_fences_before_and_after_provider(client,auth_headers,db,test_user,test_library,monkeypatch,change):
    novel,chapter,provider=setup(db,test_user,test_library,monkeypatch);capture=proof(chapter)
    value={'provider_id':provider.id,'language':'de','content_version':chapter.document['content_version'],
        'block_id':chapter.document['blocks'][0]['id'],'text_offset':0,'text_length':5,'quote':'Alice',**capture}
    if change=='stale_before':value['expected_chapter_key']=str(uuid4())
    def mutate():
        with sessionmaker(bind=db.get_bind())() as other:
            if change=='archive_after':other.get(Chapter,chapter.id).archived=True
            elif change=='append_after':other.add(Chapter(novel_id=novel.id,chapter_number=90,title='Later'))
            other.commit()
    calls=[];mock(monkeypatch,calls,mutate)
    response=client.post(f'/reader/translations/{novel.id}/0/passage-preview',headers=auth_headers,json=value)
    assert response.status_code==(200 if change=='append_after' else 409),response.text
    assert len(calls)==(0 if change=='stale_before' else 1)
    if change!='append_after':assert 'translation' not in response.json()


def test_passage_logout_during_provider_wait_never_returns_private_output(client,auth_headers,db,test_user,test_library,monkeypatch):
    from app.models.account import UserSession
    from app.services.job_lease import utcnow
    novel,chapter,provider=setup(db,test_user,test_library,monkeypatch)
    value={'provider_id':provider.id,'language':'de','content_version':chapter.document['content_version'],
        'block_id':chapter.document['blocks'][0]['id'],'text_offset':0,'text_length':5,'quote':'Alice',**proof(chapter)}
    def revoke():
        with sessionmaker(bind=db.get_bind())() as other:
            other.query(UserSession).filter_by(user_id=test_user.id).update({'revoked_at':utcnow()},synchronize_session=False)
            other.commit()
    calls=[];mock(monkeypatch,calls,revoke)
    result=client.post(f'/reader/translations/{novel.id}/0/passage-preview',headers=auth_headers,json=value)
    assert result.status_code==401 and len(calls)==1
    assert 'translation' not in result.json()


def test_migration_inferred_variant_never_claims_current_chapter_identity(client,auth_headers,db,test_user,test_library,monkeypatch):
    novel,chapter,provider=setup(db,test_user,test_library,monkeypatch)
    capture=proof(chapter)
    job_id=queue(client,auth_headers,novel,chapter,provider,capture).json()['id']
    calls=[];mock(monkeypatch,calls)
    service.process_translation(job_id,sessionmaker(bind=db.get_bind()));db.expire_all()
    job=db.get(TranslationJob,job_id);job.identity_inferred=True;db.commit()
    result=client.get(f'/reader/stories/{novel.id}/translations',headers=auth_headers)
    assert result.status_code==200
    saved=result.json()['items'][0]
    assert saved['source_identity_inferred'] and not saved['source_identity_current']
    assert saved['chapter_key'] is None and saved['chapter_number'] is None
    assert saved['source_chapter_key']==capture['expected_chapter_key']
    assert saved['exportable']
    # The private completed text remains an accessible historical artifact.
    assert client.get(f'/reader/translations/{novel.id}/{chapter.chapter_number}',headers=auth_headers).json()==[]
