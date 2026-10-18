"""Narration follows captured chapter identity through topology changes."""
from contextlib import nullcontext
from datetime import timedelta
import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from app.models import Chapter, ChapterAudioJob
from app.services import audio_job_service as audio
from app.services.chapter_document import from_text
from app.services.chapter_identity_service import identity
from tests.routes.test_audio_alignment import audio as wav
from tests.routes.test_story_audio import setup_story

PROVIDER={'id':'custom','base_url':'http://audio.invalid/v1','model':'fixture','voice':'fixture'}


def captured(chapter):
    value=identity(chapter)
    return {'expected_chapter_key':value['chapter_key'],'expected_manifest_epoch':value['manifest_epoch'],
        'expected_manifest_revision':value['manifest_revision'],'expected_content_version':chapter.document['content_version']}


def single(client,headers,chapter,proof):
    return client.post('/audio/jobs',headers=headers,json={'library_id':chapter.novel.library_id,
        'novel_id':chapter.novel_id,'chapter_number':chapter.chapter_number,'provider':PROVIDER,**proof})


def seed(db,user,library,monkeypatch,tmp_path):
    novel,_=setup_story(db,user,library,monkeypatch,tmp_path)
    chapter=db.query(Chapter).filter_by(novel_id=novel.id,chapter_number=1).one()
    chapter.chapter_number=-2;db.commit();db.refresh(chapter);db.refresh(novel.manifest_state)
    monkeypatch.setenv('DOWNLOAD_PATH',str(tmp_path))
    return novel,chapter


def transport(monkeypatch, calls, callback=None):
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            calls.append(kwargs['json']['input'])
            if callback:callback()
            return httpx.Response(200,request=httpx.Request('POST',url),content=wav(.1))
    monkeypatch.setattr(audio.httpx,'Client',Client)
    monkeypatch.setattr(audio,'heartbeat',lambda *args:nullcontext())


def test_signed_batch_captures_exact_identities_and_preserves_duplicate_outcomes(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,chapter=seed(db,test_user,test_library,monkeypatch,tmp_path)
    chapter.chapter_number=0;db.commit();db.refresh(chapter);db.refresh(novel.manifest_state)
    body={'chapter_numbers':[0,0],'provider':PROVIDER,'chapter_identities':[{'chapter_number':0,**captured(chapter)}]}
    result=client.post(f'/audio/stories/{novel.id}/jobs',headers=auth_headers,json=body)
    assert result.status_code==202,result.text
    first,second=result.json()['outcomes']
    assert first['outcome']=='queued' and second['outcome']=='already_queued'
    job=db.get(ChapterAudioJob,first['job']['id'])
    assert job.chapter_key==chapter.chapter_key and job.source_version==chapter.document['content_version']
    assert job.chapter_number_snapshot==0 and not job.identity_inferred
    for entries in ([],body['chapter_identities']*2,[{'chapter_number':2,**captured(chapter)}]):
        assert client.post(f'/audio/stories/{novel.id}/jobs',headers=auth_headers,json={**body,'chapter_identities':entries}).status_code==422


def test_stale_global_revision_rejects_new_queue_but_accepted_job_survives_append(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,chapter=seed(db,test_user,test_library,monkeypatch,tmp_path)
    proof=captured(chapter);result=single(client,auth_headers,chapter,proof);assert result.status_code==202,result.text
    job_id=result.json()['id']
    db.add(Chapter(novel_id=novel.id,chapter_number=999,title='Unrelated addition'));db.commit()
    stale=single(client,auth_headers,chapter,proof)
    assert stale.status_code==409 and stale.json()['detail']['code']=='chapter_manifest_changed'
    assert db.query(ChapterAudioJob).count()==1
    db.rollback()  # shared route fixture retains rejected-request transaction; real get_db closes it.
    calls=[];transport(monkeypatch,calls)
    audio.process_audio_job(job_id,sessionmaker(bind=db.get_bind()))
    db.expire_all();job=db.get(ChapterAudioJob,job_id)
    assert job.status=='completed' and calls
    assert job.manifest_revision==proof['expected_manifest_revision']
    result=client.get(f'/audio/jobs/{job_id}/manifest',headers=auth_headers).json()
    assert result['current_source'] and result['chapter_key']==proof['expected_chapter_key']
    assert result['manifest_revision']!=job.manifest_revision


@pytest.mark.parametrize('change',['text','archive','uuid_aba','legacy_unknown'])
def test_worker_never_calls_provider_for_changed_or_unproven_original(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path,change):
    novel,chapter=seed(db,test_user,test_library,monkeypatch,tmp_path)
    job_id=single(client,auth_headers,chapter,captured(chapter)).json()['id']
    job=db.get(ChapterAudioJob,job_id)
    if change=='text':chapter.document=from_text('Changed text.')
    elif change=='archive':chapter.archived=True
    elif change=='legacy_unknown':job.chapter_key=None
    else:
        # SQLite FK-off replacement with identical text and numeric address:
        # the database assigns a genuinely new UUID for the reused primary key.
        number,document,title,pk=chapter.chapter_number,chapter.document,chapter.title,chapter.id
        db.execute(text('DELETE FROM chapters WHERE id=:id'),{'id':pk});db.commit();db.expunge(chapter)
        db.add(Chapter(id=pk,novel_id=novel.id,chapter_number=number,document=document,content=document['plain_text'],title=title))
    db.commit()
    calls=[];transport(monkeypatch,calls)
    audio.process_audio_job(job_id,sessionmaker(bind=db.get_bind()))
    db.expire_all();job=db.get(ChapterAudioJob,job_id)
    assert calls==[] and job.status=='failed' and job.error_code=='audio_identity_review_required'
    assert client.post(f'/audio/jobs/{job_id}/retry',headers=auth_headers).status_code==409
    assert not list(tmp_path.rglob('chapter.wav'))


def test_source_revision_during_response_discards_output_without_automatic_retry(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,chapter=seed(db,test_user,test_library,monkeypatch,tmp_path)
    job_id=single(client,auth_headers,chapter,captured(chapter)).json()['id']
    def revise():
        with sessionmaker(bind=db.get_bind())() as other:
            current=other.get(Chapter,chapter.id);current.document=from_text('Revised during generation.');other.commit()
    calls=[];transport(monkeypatch,calls,revise)
    audio.process_audio_job(job_id,sessionmaker(bind=db.get_bind()))
    db.expire_all();job=db.get(ChapterAudioJob,job_id)
    assert len(calls)==1 and job.status=='failed' and job.error_code=='audio_identity_review_required'
    assert not job.audio_path and not list(tmp_path.rglob('*.wav'))


def test_completed_archived_media_manifest_and_original_display_survive(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,chapter=seed(db,test_user,test_library,monkeypatch,tmp_path)
    proof=captured(chapter);job_id=single(client,auth_headers,chapter,proof).json()['id']
    transport(monkeypatch,[]);audio.process_audio_job(job_id,sessionmaker(bind=db.get_bind()))
    db.expire_all();chapter=db.get(Chapter,chapter.id);chapter.archived=True;db.commit()
    job=client.get(f'/audio/jobs/{job_id}',headers=auth_headers).json()
    assert job['audio_ready'] and job['chapter_archived'] and job['chapter_number']==-2
    assert job['chapter_key']==proof['expected_chapter_key'] and job['chapter_number_snapshot']==-2
    assert client.get(f'/audio/jobs/{job_id}/audio',headers={**auth_headers,'Range':'bytes=0-3'}).status_code==206
    manifest=client.get(f'/audio/jobs/{job_id}/manifest',headers=auth_headers).json()
    assert manifest['precision']=='segment' and not manifest['current_source']
    assert client.get(f'/audio/stories/{novel.id}',headers=auth_headers).json()['total']==2
    exported=client.post('/audio/exports',headers=auth_headers,json={'novel_id':novel.id,'audio_job_ids':[job_id]})
    assert exported.status_code==202,exported.text
    assert exported.json()['chapters'][0]['chapter_key']==proof['expected_chapter_key']


def test_worker_expired_lease_and_replaced_attempt_cannot_publish(db,test_user,test_library,monkeypatch,tmp_path):
    novel,chapter=seed(db,test_user,test_library,monkeypatch,tmp_path)
    job=audio.queue_audio_job(db,user_id=test_user.id,library_id=test_library.id,novel_id=novel.id,chapter=chapter,provider=PROVIDER,identity_expectations=captured(chapter))
    claimed=audio.claim_audio_job(db,job.id);owner=claimed.lease_owner;attempt=claimed.attempt_count
    claimed.lease_expires_at=claimed.lease_expires_at-timedelta(hours=2);db.commit()
    assert not audio._owns_audio_job(db,job.id,owner,attempt)
    job=db.get(ChapterAudioJob,job.id);job.lease_expires_at=None;job.status='completed';db.commit()
    assert not audio._owns_audio_job(db,job.id,owner,attempt)
    assert db.get(ChapterAudioJob,job.id).status=='completed'


def test_completed_equal_text_pk_replacement_never_appears_as_current_recording(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,chapter=seed(db,test_user,test_library,monkeypatch,tmp_path)
    proof=captured(chapter);job_id=single(client,auth_headers,chapter,proof).json()['id']
    transport(monkeypatch,[]);audio.process_audio_job(job_id,sessionmaker(bind=db.get_bind()))
    db.expire_all();chapter=db.get(Chapter,chapter.id)
    pk,number,document=chapter.id,chapter.chapter_number,chapter.document
    db.execute(text('DELETE FROM chapters WHERE id=:id'),{'id':pk});db.commit();db.expunge(chapter)
    db.add(Chapter(id=pk,novel_id=novel.id,chapter_number=number,title='Replacement',document=document,content=document['plain_text']))
    db.commit()
    page=client.get(f'/audio/stories/{novel.id}',headers=auth_headers).json()
    current=next(row for row in page['chapters'] if row['chapter_number']==number)
    assert current['chapter_key']!=proof['expected_chapter_key'] and current['latest_job'] is None
    original=client.get(f'/audio/jobs/{job_id}',headers=auth_headers).json()
    assert original['chapter_key'] is None and original['chapter_number'] is None and original['audio_ready']
    assert original['source_chapter_key']==proof['expected_chapter_key']
    assert client.get(f'/audio/jobs/{job_id}/audio',headers=auth_headers).status_code==200
    rejected=client.post('/audio/exports',headers=auth_headers,json={'novel_id':novel.id,'audio_job_ids':[job_id]})
    assert rejected.status_code==409
