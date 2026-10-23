from app.models import Chapter, Novel, User, Library, VoiceProfile, ChapterAudioJob
from app.models.chapter import ContentStatus
from app.services.chapter_document import from_html
from app.services.voice_service import MODEL


def setup_story(db, user, library, monkeypatch, tmp_path):
    key=tmp_path/'voice-key';key.write_text('test-only-key-'*4)
    monkeypatch.setenv('NEXUS_LOCAL_VOICE_URL','http://host.docker.internal:8893')
    monkeypatch.setenv('NEXUS_LOCAL_VOICE_KEY_FILE',str(key))
    novel=Novel(title='Reading home',library_id=library.id);db.add(novel);db.flush()
    for number in range(1,4):
        document=from_html(f'<p>Chapter {number} words.</p>')
        db.add(Chapter(novel_id=novel.id,chapter_number=number,title=f'Chapter {number}',
            document=document,content=document['plain_text'],content_status=ContentStatus.PRESENT if number<3 else ContentStatus.MISSING))
    voice=VoiceProfile(user_id=user.id,name='Private narrator',language='German',sample=b'RIFF-private',
        transcript='Private words',model=MODEL,status='completed')
    db.add(voice);db.commit();return novel,voice


def submit(client, headers, novel, voice, numbers, **extra):
    return client.post(f'/audio/stories/{novel.id}/jobs',headers=headers,json={
        'chapter_numbers':numbers,'voice_profile_id':voice.id,**extra})


def test_story_audio_partial_batch_and_repeat_are_idempotent(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,voice=setup_story(db,test_user,test_library,monkeypatch,tmp_path)
    result=submit(client,auth_headers,novel,voice,[1,3,999,2,1])
    assert result.status_code==202
    outcomes=result.json()['outcomes']
    assert [item['outcome'] for item in outcomes]==['queued','unavailable','unavailable','queued','already_queued']
    assert outcomes[0]['job']['id']==outcomes[-1]['job']['id']
    jobs=db.query(ChapterAudioJob).all()
    assert len(jobs)==2 and all(job.provider_id=='qwen3_clone' and job.voice_profile_id==voice.id for job in jobs)
    assert all(job.provider_url=='http://host.docker.internal:8893/v1' and job.provider_model==MODEL for job in jobs)
    assert submit(client,auth_headers,novel,voice,[1,2]).json()['outcomes'][0]['outcome']=='already_queued'
    page=client.get(f'/audio/stories/{novel.id}?offset=1&limit=1',headers=auth_headers)
    assert page.status_code==200
    data=page.json()
    assert data['total']==3 and data['summary']=={'chapters':3,'downloaded':2,'queued':2,'ready':0,'needs_retry':0}
    assert len(data['chapters'])==1 and data['chapters'][0]['chapter_number']==2
    assert data['chapters'][0]['latest_job']['voice_profile_id']==voice.id
    assert data['chapters'][0]['source_version']
    missing=client.get(f'/audio/stories/{novel.id}?offset=2&limit=1',headers=auth_headers).json()['chapters'][0]
    assert not missing['downloaded'] and missing['source_version'] is None


def test_completed_audio_reuse_revised_source_and_explicit_retry(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,voice=setup_story(db,test_user,test_library,monkeypatch,tmp_path)
    queued=submit(client,auth_headers,novel,voice,[1,2]).json()['outcomes']
    complete=db.get(ChapterAudioJob,queued[0]['job']['id'])
    path=tmp_path/'finished.wav';path.write_bytes(b'RIFF-private-audio')
    complete.status='completed';complete.audio_path=str(path)
    failed=db.get(ChapterAudioJob,queued[1]['job']['id']);failed.status='failed';db.commit()
    repeated=submit(client,auth_headers,novel,voice,[1,2]).json()['outcomes']
    assert [item['outcome'] for item in repeated]==['already_ready','needs_retry']
    assert db.query(ChapterAudioJob).count()==2
    summary=client.get(f'/audio/stories/{novel.id}',headers=auth_headers).json()['summary']
    assert summary['ready']==1 and summary['needs_retry']==1
    assert client.post(f'/audio/jobs/{failed.id}/retry',headers=auth_headers).status_code==200
    assert submit(client,auth_headers,novel,voice,[2]).json()['outcomes'][0]['outcome']=='already_queued'
    chapter=db.get(Chapter,complete.chapter_id)
    chapter.document=from_html('<p>Revised words require fresh narration.</p>');db.commit()
    changed=submit(client,auth_headers,novel,voice,[1]).json()['outcomes'][0]
    assert changed['outcome']=='queued' and changed['job']['id']!=complete.id
    assert changed['job']['source_version']!=complete.source_version


def test_profile_and_notes_are_part_of_batch_identity(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,voice=setup_story(db,test_user,test_library,monkeypatch,tmp_path)
    first=submit(client,auth_headers,novel,voice,[1]).json()['outcomes'][0]['job']
    old=db.get(ChapterAudioJob,first['id']);old.status='cancelled';db.commit()
    assert submit(client,auth_headers,novel,voice,[1]).json()['outcomes'][0]['outcome']=='needs_retry'
    changed=submit(client,auth_headers,novel,voice,[1],include_author_notes=True).json()['outcomes'][0]
    assert changed['outcome']=='queued' and changed['job']['include_author_notes']
    assert client.post(f'/audio/jobs/{old.id}/retry',headers=auth_headers).status_code==409
    active=db.get(ChapterAudioJob,changed['job']['id']);active.status='cancelled';db.commit()
    second=VoiceProfile(user_id=test_user.id,name='Another narrator',language='German',sample=b'RIFF-reference',transcript='Words',model=MODEL,status='completed')
    db.add(second);db.commit()
    assert submit(client,auth_headers,novel,second,[1]).json()['outcomes'][0]['outcome']=='queued'


def test_story_audio_rejects_cross_account_unready_remote_and_oversized_batches(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,voice=setup_story(db,test_user,test_library,monkeypatch,tmp_path)
    other=User(username='other-story-owner',password='unused');db.add(other);db.flush()
    library=Library(user_id=other.id,name='Private library');db.add(library);db.flush()
    private=Novel(title='Private story',library_id=library.id);db.add(private)
    foreign=VoiceProfile(user_id=other.id,name='Private voice',language='German',sample=b'RIFF-reference',transcript='Secret',model=MODEL,status='completed')
    db.add(foreign);db.commit()
    chapter=db.query(Chapter).filter_by(novel_id=novel.id,chapter_number=1).one()
    private_audio=tmp_path/'other-account.wav';private_audio.write_bytes(b'RIFF-private')
    db.add(ChapterAudioJob(user_id=other.id,library_id=test_library.id,novel_id=novel.id,
        chapter_id=chapter.id,status='completed',provider_id='qwen3_clone',provider_url='local',
        provider_model=MODEL,provider_voice='Other private narrator',audio_path=str(private_audio)))
    db.commit()
    own_view=client.get(f'/audio/stories/{novel.id}',headers=auth_headers).json()
    assert own_view['summary']['ready']==0 and own_view['chapters'][0]['latest_job'] is None
    assert client.get(f'/audio/stories/{private.id}',headers=auth_headers).status_code==404
    assert submit(client,auth_headers,private,voice,[1]).status_code==404
    assert submit(client,auth_headers,novel,foreign,[1]).status_code==422
    voice.status='queued';db.commit()
    assert submit(client,auth_headers,novel,voice,[1]).status_code==422
    voice.status='completed';db.commit()
    for numbers in ([],list(range(1,202)),[-2147483649],[2147483648]):
        assert submit(client,auth_headers,novel,voice,numbers).status_code==422
    assert submit(client,auth_headers,novel,voice,[1],provider={'base_url':'https://paid.example'}).status_code==422
    monkeypatch.setenv('NEXUS_LOCAL_VOICE_URL','https://paid.example')
    assert submit(client,auth_headers,novel,voice,[1]).status_code==422
    assert db.query(ChapterAudioJob).filter_by(user_id=test_user.id).count()==0
    assert client.get(f'/audio/stories/{novel.id}?limit=201',headers=auth_headers).status_code==422
    assert client.get(f'/audio/stories/{novel.id}?offset=-1',headers=auth_headers).status_code==422


def test_explicit_retry_resets_delay_and_lease_but_preserves_completed_segments(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    from datetime import datetime, timedelta
    from app.models import ChapterAudioPart
    novel,voice=setup_story(db,test_user,test_library,monkeypatch,tmp_path)
    result=submit(client,auth_headers,novel,voice,[1]).json()['outcomes'][0]
    job=db.get(ChapterAudioJob,result['job']['id'])
    job.status='retry_wait';job.attempt_count=3;job.next_attempt_at=datetime.now()+timedelta(hours=1)
    job.lease_owner='stale-worker';job.lease_expires_at=datetime.now()+timedelta(hours=1)
    job.cancelled_at=datetime.now();job.completed_parts=1
    part=db.query(ChapterAudioPart).filter_by(job_id=job.id,part_index=0).one()
    part.status='completed';part.audio_path='/private/completed.wav';db.commit()
    response=client.post(f'/audio/jobs/{job.id}/retry',headers=auth_headers)
    assert response.status_code==200 and response.json()['status']=='queued'
    db.refresh(job);db.refresh(part)
    assert job.next_attempt_at is None and job.lease_owner is None and job.lease_expires_at is None
    assert job.cancelled_at is None and job.attempt_count==0 and job.completed_parts==1
    assert part.status=='completed' and part.audio_path=='/private/completed.wav'


def test_one_unavailable_item_keeps_successfully_queued_work(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    from app.routers import audio
    novel,voice=setup_story(db,test_user,test_library,monkeypatch,tmp_path)
    original=audio.queue_audio_job
    def queue(db, **kwargs):
        if kwargs['chapter'].chapter_number==2:
            raise ValueError('Chapter changed during request')
        return original(db, **kwargs)
    monkeypatch.setattr(audio,'queue_audio_job',queue)
    result=submit(client,auth_headers,novel,voice,[1,2]).json()['outcomes']
    assert [item['outcome'] for item in result]==['queued','unavailable']
    assert db.query(ChapterAudioJob).filter_by(user_id=test_user.id).count()==1


def generic_provider(**overrides):
    return {'id':'kokoro_mps','base_url':'http://speech-fixture:8880/v1/',
        'model':'fixture-model','voice':'fixture-voice','language_code':'en','execution_mode':'server',**overrides}


def test_generic_server_provider_mixed_batch_and_completed_reuse(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,_=setup_story(db,test_user,test_library,monkeypatch,tmp_path)
    # Generic server narration remains available without the clone service.
    monkeypatch.delenv('NEXUS_LOCAL_VOICE_URL')
    payload={'chapter_numbers':[1,3,999,2,1],'provider':generic_provider()}
    response=client.post(f'/audio/stories/{novel.id}/jobs',headers=auth_headers,json=payload)
    assert response.status_code==202
    outcomes=response.json()['outcomes']
    assert [item['outcome'] for item in outcomes]==['queued','unavailable','unavailable','queued','already_queued']
    job=db.get(ChapterAudioJob,outcomes[0]['job']['id'])
    assert job.provider_id=='kokoro_mps' and job.voice_profile_id is None
    assert job.provider_url=='http://speech-fixture:8880/v1' and job.provider_language=='en'
    path=tmp_path/'generic.wav';path.write_bytes(b'RIFF-fixture')
    job.status='completed';job.audio_path=str(path);db.commit()
    payload['chapter_numbers']=[1]
    reused=client.post(f'/audio/stories/{novel.id}/jobs',headers=auth_headers,json=payload).json()['outcomes'][0]
    assert reused['outcome']=='already_ready' and reused['job']['id']==job.id
    payload['provider']['base_url']=payload['provider']['base_url'].rstrip('/')
    assert client.post(f'/audio/stories/{novel.id}/jobs',headers=auth_headers,json=payload).json()['outcomes'][0]['outcome']=='already_ready'
    assert db.query(ChapterAudioJob).count()==2


def test_generic_snapshot_identity_does_not_reuse_other_narration(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,_=setup_story(db,test_user,test_library,monkeypatch,tmp_path)
    payload={'chapter_numbers':[1],'provider':generic_provider()}
    for field,value in [('id','custom'),('base_url','http://other-fixture/v1'),('model','second-model'),('voice','second-voice'),('language_code','de')]:
        # Each provider snapshot remains distinct, even with the same prose.
        payload['provider']=generic_provider()
        first=client.post(f'/audio/stories/{novel.id}/jobs',headers=auth_headers,json=payload).json()['outcomes'][0]
        old=db.get(ChapterAudioJob,first['job']['id']);old.status='failed';db.commit()
        payload['provider']=generic_provider(**{field:value})
        changed=client.post(f'/audio/stories/{novel.id}/jobs',headers=auth_headers,json=payload).json()['outcomes'][0]
        assert changed['outcome']=='queued' and changed['job']['id']!=old.id
        new=db.get(ChapterAudioJob,changed['job']['id']);new.status='failed';db.commit()
    assert client.post(f'/audio/stories/{novel.id}/jobs',headers=auth_headers,json=payload).json()['outcomes'][0]['outcome']=='needs_retry'


def test_batch_provider_choice_and_shared_single_policy(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,voice=setup_story(db,test_user,test_library,monkeypatch,tmp_path)
    endpoint=f'/audio/stories/{novel.id}/jobs'
    for selection in ({},{'voice_profile_id':voice.id,'provider':generic_provider()}):
        assert client.post(endpoint,headers=auth_headers,json={'chapter_numbers':[1],**selection}).status_code==422
    assert client.post(endpoint,headers=auth_headers,json={'chapter_numbers':[1],'provider':generic_provider(execution_mode='browser')}).status_code==409
    assert client.post(endpoint,headers=auth_headers,json={'chapter_numbers':[1],'provider':generic_provider(id='qwen3_clone')}).status_code==422
    single={'library_id':test_library.id,'novel_id':novel.id,'chapter_number':1,'provider':generic_provider(execution_mode='browser')}
    assert client.post('/audio/jobs',headers=auth_headers,json=single).status_code==409
    single['provider']=generic_provider(id='qwen3_clone')
    assert client.post('/audio/jobs',headers=auth_headers,json=single).status_code==422
    single['provider']=generic_provider()
    assert client.post('/audio/jobs',headers=auth_headers,json=single).status_code==202


def test_story_latest_job_prioritizes_active_then_recent_update(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    from datetime import datetime, timedelta
    novel,voice=setup_story(db,test_user,test_library,monkeypatch,tmp_path)
    old_id=submit(client,auth_headers,novel,voice,[1]).json()['outcomes'][0]['job']['id']
    old=db.get(ChapterAudioJob,old_id);old.status='cancelled';db.commit()
    newer_id=submit(client,auth_headers,novel,voice,[1],include_author_notes=True).json()['outcomes'][0]['job']['id']
    newer=db.get(ChapterAudioJob,newer_id);newer.status='failed';db.commit()
    assert newer.id>old.id
    assert client.post(f'/audio/jobs/{old.id}/retry',headers=auth_headers).status_code==200
    newer.updated_at=datetime.now()+timedelta(hours=1);db.commit()
    data=client.get(f'/audio/stories/{novel.id}',headers=auth_headers).json()
    assert data['chapters'][0]['latest_job']['id']==old.id and data['summary']['queued']==1
    old.status='completed';old.updated_at=datetime.now()+timedelta(hours=2);db.commit()
    data=client.get(f'/audio/stories/{novel.id}',headers=auth_headers).json()
    assert data['chapters'][0]['latest_job']['id']==old.id and data['summary']['needs_retry']==0


def test_qwen_chunk_choice_persists_coalesces_and_completed_settings_do_not_alias(client, auth_headers, db, test_user, test_library, monkeypatch, tmp_path):
    from app.models import ChapterAudioPart
    novel, voice = setup_story(db, test_user, test_library, monkeypatch, tmp_path)
    chapter = db.query(Chapter).filter_by(novel_id=novel.id, chapter_number=1).one()
    chapter.document = from_html(''.join('<p>' + ('Sentence for paragraph %s. ' % i) * 5 + '</p>' for i in range(30)))
    chapter.content = chapter.document['plain_text']; db.commit()
    first = submit(client, auth_headers, novel, voice, [1]).json()['outcomes'][0]['job']
    old = db.get(ChapterAudioJob, first['id']); old.status = 'completed'
    path = tmp_path/'previous.wav'; path.write_bytes(b'RIFF'); old.audio_path=str(path); db.commit()
    newer = submit(client, auth_headers, novel, voice, [1], qwen_chunk_size=3000)
    assert newer.status_code == 202, newer.text
    current = newer.json()['outcomes'][0]['job']
    assert current['id'] != old.id and current['qwen_chunk_size'] == 3000 and current['generation_token_limit'] == 2400
    assert current['total_parts'] < first['total_parts'] / 2
    parts = db.query(ChapterAudioPart).filter_by(job_id=current['id']).order_by(ChapterAudioPart.part_index).all()
    assert all(len(p.text) <= 3000 for p in parts)
    spans = [span for p in parts for span in (p.source_spans or [])]
    assert [s['block_id'] for s in spans] == [b['id'] for b in chapter.document['blocks']]
    assert ' '.join(p.text for p in parts[1:]) == ' '.join(b['text'] for b in chapter.document['blocks'])
    for part in parts[1:]:
        assert part.text_length == part.source_spans[0]['text_length']
    assert submit(client, auth_headers, novel, voice, [2], qwen_chunk_size=2000).status_code == 422
    spans_before = [p.source_spans for p in parts]
    job = db.get(ChapterAudioJob, current['id']); job.status='completed'
    for part in parts: part.status='completed'; part.duration_seconds=1
    db.commit()
    repaired = client.post(f"/audio/jobs/{job.id}/parts/1/retry", headers=auth_headers)
    assert repaired.status_code == 200, repaired.text
    db.refresh(job)
    assert job.qwen_chunk_size == 3000 and job.generation_token_limit == 2400
    assert [p.source_spans for p in db.query(ChapterAudioPart).filter_by(job_id=job.id).order_by(ChapterAudioPart.part_index)] == spans_before
