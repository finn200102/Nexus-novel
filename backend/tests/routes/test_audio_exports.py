import io
import json
from pathlib import Path
from contextlib import nullcontext
from datetime import timedelta
import wave

from sqlalchemy.orm import sessionmaker
from app.models import Chapter, ChapterAudioJob, Novel, User
from app.models.audio_export import AudioExportJob
from app.models.account import UserSession
from app.services import audio_export_service as service
from app.services.chapter_document import from_html
from app.services.job_lease import claim, recover_expired, utcnow
from app.auth.jwt import verify_token


def pcm(seconds=1,rate=24000):
    out=io.BytesIO()
    with wave.open(out,'wb') as recording:
        recording.setnchannels(1);recording.setsampwidth(2);recording.setframerate(rate)
        recording.writeframes(b'\x00\x01'*int(seconds*rate))
    return out.getvalue()


def recordings(db,user,library,monkeypatch,tmp_path):
    monkeypatch.setenv('DOWNLOAD_PATH',str(tmp_path))
    monkeypatch.setattr(service,'heartbeat',lambda *args:nullcontext())
    novel=Novel(title='Private audiobook #1; = \\ title',library_id=library.id);db.add(novel);db.flush()
    jobs=[]
    for number,rate in ((1,16000),(2,24000)):
        title='Chapter #1; = \\ title\n[CHAPTER]' if number==1 else 'Chapter two'
        document=from_html(f'<p>Original chapter {number}.</p>')
        chapter=Chapter(novel_id=novel.id,chapter_number=number,title=title,content=document['plain_text'],document=document)
        db.add(chapter);db.flush()
        job=ChapterAudioJob(user_id=user.id,library_id=library.id,novel_id=novel.id,chapter_id=chapter.id,
            status='completed',provider_id='custom',provider_url='fixture',provider_model='fixture',provider_voice='fixture',
            source_version=document['content_version'],total_parts=1,completed_parts=1)
        from app.services.chapter_identity_service import identity
        db.refresh(chapter)
        captured=identity(chapter)
        job.chapter_key=captured["chapter_key"];job.manifest_epoch=captured["manifest_epoch"];job.manifest_revision=captured["manifest_revision"]
        db.add(job);db.flush()
        path=tmp_path/'audio'/str(user.id)/str(novel.id)/str(chapter.id)/str(job.id)/'chapter.wav'
        path.parent.mkdir(parents=True);path.write_bytes(pcm(1 if number==1 else 1.5,rate))
        job.audio_path=str(path);job.audio_bytes=path.stat().st_size;jobs.append(job)
    db.commit();return novel,jobs


def create(client,headers,novel,jobs):
    return client.post('/audio/exports',headers=headers,json={'novel_id':novel.id,'audio_job_ids':[job.id for job in jobs]})


def test_export_real_m4b_markers_range_and_idempotence(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,jobs=recordings(db,test_user,test_library,monkeypatch,tmp_path)
    response=create(client,auth_headers,novel,list(reversed(jobs)))
    assert response.status_code==202
    data=response.json();export_id=data['id']
    assert [row['chapter_number'] for row in data['chapters']]==[1,2]
    assert 'path' not in json.dumps(data) and str(tmp_path) not in json.dumps(data)
    assert create(client,auth_headers,novel,jobs).json()['id']==export_id
    service.process_export_job(export_id,sessionmaker(bind=db.get_bind()))
    db.expire_all()
    completed=client.get(f'/audio/exports/{export_id}',headers=auth_headers).json()
    assert completed['status']=='completed',completed
    assert completed['file_ready'] and completed['completed_chapters']==2
    assert completed['duration_seconds']==2.5 and completed['chapters'][1]['start_seconds']==1
    assert completed['chapters'][0]['source_version']==jobs[0].source_version
    assert create(client,auth_headers,novel,jobs).json()['id']==export_id
    result=client.get(f'/audio/exports/{export_id}/file',headers={**auth_headers,'Range':'bytes=0-15'})
    assert result.status_code==206 and len(result.content)==16
    assert result.headers['content-type']=='audio/mp4'
    assert result.headers['content-disposition'].endswith(f'"story-{novel.id}.m4b"')
    assert result.headers['cache-control']=='private, no-store'
    assert b'ftyp' in result.content
    assert service.audio_export_storage_bytes(test_user.id)>=completed['audio_bytes']
    export_root=tmp_path/'audio-exports';moved_exports=tmp_path/'moved-exports'
    export_root.rename(moved_exports);export_root.symlink_to(moved_exports,target_is_directory=True)
    try:
        assert client.get(f'/audio/exports/{export_id}/file',headers=auth_headers).status_code==404
    finally:
        export_root.unlink();moved_exports.rename(export_root)
    # Exported bytes are independent of later removal of original recordings.
    Path(jobs[0].audio_path).unlink()
    assert client.get(f'/audio/exports/{export_id}/file',headers=auth_headers).status_code==200
    assert client.delete(f'/audio/exports/{export_id}',headers=auth_headers).status_code==204
    assert service.audio_export_storage_bytes(test_user.id)==0
    assert Path(jobs[1].audio_path).is_file()


def test_export_private_inputs_and_owner_boundaries(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,jobs=recordings(db,test_user,test_library,monkeypatch,tmp_path)
    foreign=User(username='foreign-export-owner',password='unused');db.add(foreign);db.commit()
    jobs[1].user_id=foreign.id;db.commit()
    assert create(client,auth_headers,novel,jobs).status_code==404
    jobs[1].user_id=test_user.id;jobs[1].status='processing';db.commit()
    assert create(client,auth_headers,novel,jobs).status_code==409
    jobs[1].status='completed';db.commit()
    created=create(client,auth_headers,novel,jobs).json();export=db.get(AudioExportJob,created['id'])
    export.user_id=foreign.id;db.commit()
    assert client.get('/audio/exports',headers=auth_headers).json()==[]
    for suffix in ('','/file','/cancel','/retry','/download'):
        method=client.get if suffix in ('','/file') else client.post
        assert method(f'/audio/exports/{export.id}{suffix}',headers=auth_headers).status_code==404
    assert client.delete(f'/audio/exports/{export.id}',headers=auth_headers).status_code==404


def test_source_path_symlink_and_same_size_replacement_rejected(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,jobs=recordings(db,test_user,test_library,monkeypatch,tmp_path)
    original=Path(jobs[0].audio_path)
    outside=tmp_path.parent/'outside-export-source.wav';outside.write_bytes(pcm())
    jobs[0].audio_path=str(outside);db.commit()
    assert create(client,auth_headers,novel,jobs).status_code==409
    link=original.parent/'linked.wav';link.symlink_to(outside)
    jobs[0].audio_path=str(link);db.commit()
    assert create(client,auth_headers,novel,jobs).status_code==409
    jobs[0].audio_path=str(original);db.commit()
    audio_root=tmp_path/'audio';moved_audio=tmp_path/'moved-audio'
    audio_root.rename(moved_audio);audio_root.symlink_to(moved_audio,target_is_directory=True)
    try:
        assert create(client,auth_headers,novel,jobs).status_code==409
    finally:
        audio_root.unlink();moved_audio.rename(audio_root)
    result=create(client,auth_headers,novel,jobs).json()
    data=bytearray(original.read_bytes());data[-1]^=1;original.write_bytes(data)
    service.process_export_job(result['id'],sessionmaker(bind=db.get_bind()))
    db.expire_all();job=db.get(AudioExportJob,result['id'])
    assert job.status=='failed' and job.error_code=='source_changed'
    assert job.audio_path is None
    outside.unlink()


def test_missing_source_and_truncated_pcm_fail_actionably(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,jobs=recordings(db,test_user,test_library,monkeypatch,tmp_path)
    result=create(client,auth_headers,novel,jobs).json()
    Path(jobs[0].audio_path).unlink()
    service.process_export_job(result['id'],sessionmaker(bind=db.get_bind()))
    db.expire_all();job=db.get(AudioExportJob,result['id'])
    assert job.status=='failed' and job.error_code=='source_missing'
    assert 'Restore' in job.error
    assert client.post(f'/audio/exports/{job.id}/retry',headers=auth_headers).json()['status']=='queued'
    assert client.delete(f'/audio/exports/{job.id}',headers=auth_headers).status_code==409
    assert client.post(f'/audio/exports/{job.id}/cancel',headers=auth_headers).status_code==200
    assert client.delete(f'/audio/exports/{job.id}',headers=auth_headers).status_code==204
    damaged=Path(jobs[1].audio_path);damaged.write_bytes(pcm()[:-100])
    queued=create(client,auth_headers,novel,[jobs[1]]).json()
    service.process_export_job(queued['id'],sessionmaker(bind=db.get_bind()))
    db.expire_all();job=db.get(AudioExportJob,queued['id'])
    assert job.status=='failed' and job.error_code=='invalid_audio'


def test_worker_interruption_lease_recovery_and_stale_completion_discard(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,jobs=recordings(db,test_user,test_library,monkeypatch,tmp_path)
    result=create(client,auth_headers,novel,jobs).json()
    job=db.get(AudioExportJob,result['id'])
    assert claim(db,AudioExportJob,job.id,worker_id='old') is not None
    assert claim(db,AudioExportJob,job.id,worker_id='second') is None
    job.lease_expires_at=utcnow()-timedelta(seconds=1);db.commit()
    assert recover_expired(db,AudioExportJob)==1
    def encode(descriptors,measured,title,output,directory,worker_db,job_id,owner,should_stop,**kwargs):
        output.write_bytes(b'not promoted')
        client.post(f'/audio/exports/{job_id}/cancel',headers=auth_headers)
    monkeypatch.setattr(service,'_encode',encode)
    service.process_export_job(job.id,sessionmaker(bind=db.get_bind()))
    db.expire_all();db.refresh(job)
    assert job.status=='cancelled' and job.audio_path is None
    assert not list((tmp_path/'audio-exports').rglob('*.m4b'))
    assert all(Path(audio.audio_path).exists() for audio in jobs)


def test_download_ticket_is_export_scoped_and_revoked_with_session(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,jobs=recordings(db,test_user,test_library,monkeypatch,tmp_path)
    export_id=create(client,auth_headers,novel,jobs).json()['id']
    service.process_export_job(export_id,sessionmaker(bind=db.get_bind()))
    ticket=client.post(f'/audio/exports/{export_id}/download',headers=auth_headers)
    assert ticket.status_code==200
    cookie=ticket.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'SameSite=strict' in cookie and 'Max-Age=300' in cookie
    assert f'Path=/audio/exports/{export_id}/file' in cookie
    assert client.get(ticket.json()['url'],headers={'Range':'bytes=0-15'}).status_code==206
    # Tickets cannot access any other export or list private account data.
    assert client.get('/audio/exports').status_code==401
    claims=verify_token(auth_headers['Authorization'].split(' ',1)[1])
    session=db.get(UserSession,claims['session_id']);session.revoked_at=utcnow();db.commit()
    assert client.get(ticket.json()['url']).status_code==401


def test_export_purge_hooks_preserve_chapter_audio(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,jobs=recordings(db,test_user,test_library,monkeypatch,tmp_path)
    export_id=create(client,auth_headers,novel,jobs).json()['id']
    assert service.cancel_user_exports(db,test_user.id)==1;db.commit()
    service.purge_export_files(test_user.id)
    db.refresh(db.get(AudioExportJob,export_id))
    assert db.get(AudioExportJob,export_id).status=='cancelled'
    assert all(Path(job.audio_path).is_file() for job in jobs)


def test_export_shutdown_terminates_encoder_and_preserves_originals(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,jobs=recordings(db,test_user,test_library,monkeypatch,tmp_path)
    export_id=create(client,auth_headers,novel,jobs).json()['id']
    processes=[]
    class Process:
        def __init__(self,*args,**kwargs):
            self.returncode=None;self.terminated=False;processes.append(self)
        def poll(self):return self.returncode
        def terminate(self):self.terminated=True;self.returncode=-15
        def wait(self,timeout):return self.returncode
        def kill(self):self.returncode=-9
    monkeypatch.setattr(service.subprocess,'Popen',Process)
    service.process_export_job(export_id,sessionmaker(bind=db.get_bind()),should_stop=lambda:bool(processes))
    db.expire_all();job=db.get(AudioExportJob,export_id)
    assert job.status=='retry_wait' and job.error_code=='worker_stopped'
    assert len(processes)==1 and processes[0].terminated
    assert job.audio_path is None and all(Path(audio.audio_path).exists() for audio in jobs)
    assert not list((tmp_path/'audio-exports').rglob('*.m4b'))


def test_download_ticket_proxy_path_scope_and_account_switch(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    from app.auth.sessions import start_session
    novel,jobs=recordings(db,test_user,test_library,monkeypatch,tmp_path)
    export_id=create(client,auth_headers,novel,jobs).json()['id']
    service.process_export_job(export_id,sessionmaker(bind=db.get_bind()))
    ticket=client.post(f'/audio/exports/{export_id}/download',headers={**auth_headers,
        'x-forwarded-prefix':'/api','x-forwarded-host':'reader.example','x-forwarded-proto':'https'})
    assert ticket.json()['url']==f'/api/audio/exports/{export_id}/file'
    assert f'Path=/api/audio/exports/{export_id}/file' in ticket.headers['set-cookie']
    assert 'Secure' in ticket.headers['set-cookie']
    # Request a direct-API ticket too; both deployment paths remain scoped.
    assert client.post(f'/audio/exports/{export_id}/download',headers=auth_headers).status_code==200
    other=User(username='new-browser-export-account',password='unused');db.add(other);db.flush()
    _,refresh=start_session(db,other);db.commit()
    client.cookies.set('nexus_refresh',refresh)
    assert client.get(f'/audio/exports/{export_id}/file').status_code==401
    client.cookies.delete('nexus_refresh')
    test_user.is_disabled=True;db.commit()
    assert client.get(f'/audio/exports/{export_id}/file').status_code==401


def test_export_selection_rejects_duplicate_chapters_and_cannot_generate_tts(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,jobs=recordings(db,test_user,test_library,monkeypatch,tmp_path)
    invalid=client.post('/audio/exports',headers=auth_headers,json={'novel_id':novel.id,'audio_job_ids':[jobs[0].id,jobs[0].id]})
    assert invalid.status_code==422
    extra=client.post('/audio/exports',headers=auth_headers,json={'novel_id':novel.id,'audio_job_ids':[jobs[0].id],'provider':{'id':'paid'}})
    assert extra.status_code==422
    duplicate=ChapterAudioJob(user_id=test_user.id,library_id=test_library.id,novel_id=novel.id,chapter_id=jobs[0].chapter_id,
        status='completed',provider_id='custom',provider_url='unused',provider_model='unused',provider_voice='unused',
        audio_path=jobs[0].audio_path,source_version=jobs[0].source_version)
    db.add(duplicate);db.commit()
    assert create(client,auth_headers,novel,[jobs[0],duplicate]).status_code==409
    assert db.query(AudioExportJob).count()==0
    assert db.query(ChapterAudioJob).count()==3


def test_retry_wait_clears_previous_attempt_progress_before_encoding(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,jobs=recordings(db,test_user,test_library,monkeypatch,tmp_path)
    export_id=create(client,auth_headers,novel,jobs).json()['id']
    job=db.get(AudioExportJob,export_id)
    job.status='retry_wait';job.completed_chapters=2;job.next_attempt_at=utcnow()-timedelta(seconds=1);db.commit()
    entered=[]
    def encode(descriptors,measured,title,output,directory,worker_db,job_id,owner,should_stop,**kwargs):
        current=worker_db.get(AudioExportJob,job_id)
        assert current.completed_chapters==0 and current.lease_owner==owner and current.status=='processing'
        entered.append(True)
        raise service.ExportError('worker_stopped','Export interrupted by worker shutdown. Completed recordings are preserved; retry the export.')
    monkeypatch.setattr(service,'_encode',encode)
    service.process_export_job(export_id,sessionmaker(bind=db.get_bind()))
    db.expire_all();db.refresh(job)
    assert entered==[True] and job.completed_chapters==0 and job.status=='retry_wait'
    assert all(Path(audio.audio_path).exists() for audio in jobs)


def test_queue_hash_deadline_covers_whole_selection_and_retains_no_job(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    from types import SimpleNamespace
    novel,jobs=recordings(db,test_user,test_library,monkeypatch,tmp_path)
    clock=[0.0]
    original=service._signature
    calls=[]
    def signature(path,*,deadline=None):
        calls.append(deadline)
        clock[0]+=7
        return original(path,deadline=deadline)
    monkeypatch.setattr(service,'time',SimpleNamespace(monotonic=lambda:clock[0]))
    monkeypatch.setattr(service,'_signature',signature)
    result=create(client,auth_headers,novel,jobs)
    assert result.status_code==409 and 'Choose fewer chapters' in result.json()['detail']
    assert calls==[12,12] and db.query(AudioExportJob).count()==0
    assert all(Path(audio.audio_path).is_file() for audio in jobs)


def test_stale_owner_cannot_reset_replacement_worker_progress(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    from types import SimpleNamespace
    from sqlalchemy import update
    novel,jobs=recordings(db,test_user,test_library,monkeypatch,tmp_path)
    export_id=create(client,auth_headers,novel,jobs).json()['id']
    original=service.claim
    def replaced_claim(worker_db,model,job_id):
        claimed=original(worker_db,model,job_id)
        stale=SimpleNamespace(id=claimed.id,lease_owner=claimed.lease_owner,user_id=claimed.user_id,
            attempt_count=claimed.attempt_count,max_attempts=claimed.max_attempts)
        worker_db.execute(update(AudioExportJob).where(AudioExportJob.id==job_id).values(
            lease_owner='replacement-worker',completed_chapters=1))
        worker_db.commit()
        return stale
    monkeypatch.setattr(service,'claim',replaced_claim)
    service.process_export_job(export_id,sessionmaker(bind=db.get_bind()))
    db.expire_all();job=db.get(AudioExportJob,export_id)
    assert job.status=='processing' and job.lease_owner=='replacement-worker' and job.completed_chapters==1
    assert job.audio_path is None
