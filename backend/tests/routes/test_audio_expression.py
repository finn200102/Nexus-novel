import json
import wave
import pytest
from app.models import Chapter, ChapterAudioJob
from app.models.audio_job import ChapterAudioPart
from app.models.translation import ReaderProvider
from app.services import audio_job_service as audio, audio_preparation as expression
from tests.routes.test_story_audio import setup_story, submit


def local_provider(db, user, monkeypatch):
    monkeypatch.setenv('NEXUS_LOCAL_AI_BASE_URL', 'http://127.0.0.1:8080/v1')
    provider = ReaderProvider(user_id=user.id, name='Local narration', kind='local',base_url='http://127.0.0.1:8080/v1',model='qwen3.8-27b',enabled=True)
    db.add(provider);db.commit();return provider


def fish_story(db,user,library,monkeypatch,tmp_path):
    novel,voice=setup_story(db,user,library,monkeypatch,tmp_path)
    monkeypatch.setenv('NEXUS_FISH_VOICE_URL','http://127.0.0.1:8895')
    monkeypatch.setenv('NEXUS_FISH_VOICE_KEY_FILE',str(tmp_path/'voice-key'))
    voice.model='fishaudio/s2-pro';db.commit();return novel,voice


def test_insertions_preserve_source():
    text='Hello, brave reader.'
    assert expression.render(text,json.dumps({'insertions':[{'offset':7,'tag':'emphasis'}]}))=='Hello, [emphasis]brave reader.'
    assert expression.render(text,'{"insertions":[]}')==text
    assert expression.render(text,json.dumps({'insertions':[{'quote':'brave','tag':'emphasis'}]}))=='Hello, [emphasis]brave reader.'
    with pytest.raises(ValueError):expression.render('word word',json.dumps({'insertions':[{'quote':'word','tag':'emphasis'}]}))
    for bad in [{'text':'Rewrite'},{'insertions':[{'offset':1,'tag':'emphasis'}]}, {'insertions':[{'offset':True,'tag':'pause'}]}, {'insertions':[{'offset':0,'tag':'command'}]}, {'insertions':[{'offset':0,'tag':'sad'}]*2}]:
        with pytest.raises(ValueError):expression.render(text,json.dumps(bad))


def test_fish_routing_and_variant_separation(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,voice=fish_story(db,test_user,test_library,monkeypatch,tmp_path)
    provider=local_provider(db,test_user,monkeypatch)
    plain=db.get(ChapterAudioJob,submit(client,auth_headers,novel,voice,[1]).json()['outcomes'][0]['job']['id'])
    plain.status='completed';path=tmp_path/'plain.wav';path.write_bytes(b'RIFF');plain.audio_path=str(path);db.commit()
    assert plain.provider_id=='fish_clone' and plain.provider_url=='http://127.0.0.1:8895/v1'
    response=submit(client,auth_headers,novel,voice,[1],preparation_provider_id=provider.id)
    assert response.status_code==202,response.text
    prepared=db.get(ChapterAudioJob,response.json()['outcomes'][0]['job']['id'])
    assert prepared.id!=plain.id and prepared.preparation['model']=='qwen3.8-27b' and prepared.preparation_version


def test_qwen_and_remote_preparation_rejected(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,voice=setup_story(db,test_user,test_library,monkeypatch,tmp_path)
    provider=local_provider(db,test_user,monkeypatch)
    assert submit(client,auth_headers,novel,voice,[1],preparation_provider_id=provider.id).status_code==422
    novel,voice=fish_story(db,test_user,test_library,monkeypatch,tmp_path)
    provider.kind='openai';db.commit()
    assert submit(client,auth_headers,novel,voice,[1],preparation_provider_id=provider.id).status_code==422


def test_preview_keeps_original(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,voice=fish_story(db,test_user,test_library,monkeypatch,tmp_path)
    provider=local_provider(db,test_user,monkeypatch)
    from app.services import reader_provider
    monkeypatch.setattr(reader_provider,'invoke',lambda *args,**kwargs:('{"insertions":[{"offset":0,"tag":"calm"}]}',1,1,0))
    chapter=db.query(Chapter).filter_by(novel_id=novel.id,chapter_number=1).one();original=chapter.document
    identity=client.get(f'/audio/stories/{novel.id}',headers=auth_headers).json()['chapters'][0]
    expected={'expected_'+k:identity[k] for k in ('chapter_key','manifest_epoch','manifest_revision')}
    expected['expected_content_version']=identity['source_version']
    response=client.post('/audio/expression-preview',headers=auth_headers,json={'novel_id':novel.id,'chapter_number':1,'provider_id':provider.id,**expected})
    assert response.status_code==200,response.text
    assert all(p['text']=='[calm]'+p['original_text'] for p in response.json()['parts'])
    db.refresh(chapter);assert chapter.document==original and db.query(ChapterAudioJob).count()==0


def test_repair_retains_other_passages(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,voice=fish_story(db,test_user,test_library,monkeypatch,tmp_path)
    job=db.get(ChapterAudioJob,submit(client,auth_headers,novel,voice,[1]).json()['outcomes'][0]['job']['id'])
    parts=db.query(ChapterAudioPart).filter_by(job_id=job.id).order_by(ChapterAudioPart.part_index).all()
    for part in parts:part.status='completed';part.synthesis_text='[calm]'+part.text
    job.status='completed';job.completed_parts=len(parts);db.commit()
    assert client.get(f'/audio/jobs/{job.id}/parts',headers=auth_headers).status_code==200
    response=client.post(f'/audio/jobs/{job.id}/parts/{parts[0].part_index}/retry',headers=auth_headers)
    assert response.status_code==200,response.text
    db.expire_all();assert db.get(ChapterAudioPart,parts[0].id).status=='queued'
    assert all(db.get(ChapterAudioPart,p.id).status=='completed' for p in parts[1:])
    assert db.get(ChapterAudioPart,parts[0].id).synthesis_text.startswith('[calm]')
    assert client.post(f'/audio/jobs/{job.id}/parts/{parts[0].part_index}/retry',headers=auth_headers).status_code==409


def test_failed_assembly_preserves_recording(tmp_path):
    final=tmp_path/'chapter.wav';final.write_bytes(b'old recording')
    invalid=tmp_path/'part.wav';invalid.write_bytes(b'invalid')
    with pytest.raises(wave.Error):audio._write_wav_parts([invalid],final)
    assert final.read_bytes()==b'old recording'


def test_changed_chapter_during_preparation_never_calls_tts(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    from sqlalchemy.orm import sessionmaker
    from app.services.chapter_document import from_html
    from tests.routes.test_audio_chapter_identity import transport
    novel,voice=fish_story(db,test_user,test_library,monkeypatch,tmp_path)
    provider=local_provider(db,test_user,monkeypatch)
    queued=submit(client,auth_headers,novel,voice,[1],preparation_provider_id=provider.id)
    assert queued.status_code==202,queued.text
    job_id=queued.json()['outcomes'][0]['job']['id']
    chapter=db.query(Chapter).filter_by(novel_id=novel.id,chapter_number=1).one()
    factory=sessionmaker(bind=db.get_bind())
    def changed_source(*args,**kwargs):
        # A separate editor commits while the provider is generating annotations.
        with factory() as editor:
            current=editor.get(Chapter,chapter.id)
            current.document=from_html('<p>Changed while narration was being prepared.</p>')
            editor.commit()
        return '{"insertions":[{"offset":0,"tag":"calm"}]}',1,1,0
    monkeypatch.setattr(expression,'invoke',changed_source)
    calls=[];transport(monkeypatch,calls)
    monkeypatch.setenv('DOWNLOAD_PATH',str(tmp_path))
    audio.process_audio_job(job_id,factory)
    db.expire_all();job=db.get(ChapterAudioJob,job_id)
    assert calls==[] and job.status=='failed'
    assert job.error_code=='audio_identity_review_required'
    assert all(part.synthesis_text is None for part in db.query(ChapterAudioPart).filter_by(job_id=job_id))


def test_worker_repair_generates_only_selected_part_and_reassembles(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    from pathlib import Path
    from sqlalchemy.orm import sessionmaker
    from tests.routes.test_audio_chapter_identity import transport
    from tests.routes.test_audio_alignment import audio as wav
    novel,voice=fish_story(db,test_user,test_library,monkeypatch,tmp_path)
    job_id=submit(client,auth_headers,novel,voice,[1]).json()['outcomes'][0]['job']['id']
    job=db.get(ChapterAudioJob,job_id)
    parts=db.query(ChapterAudioPart).filter_by(job_id=job_id).order_by(ChapterAudioPart.part_index).all()
    assert len(parts)>=2
    original={}
    for part in parts:
        path=tmp_path/f'original-{part.part_index}.wav';path.write_bytes(wav(.2))
        part.status='completed';part.audio_path=str(path);part.duration_seconds=.2
        part.synthesis_text='[calm]'+part.text
        original[part.id]=(str(path),path.read_bytes(),part.duration_seconds)
    final=tmp_path/'old-chapter.wav';audio._write_wav_parts([Path(part.audio_path) for part in parts],final)
    job.status='completed';job.audio_path=str(final);job.completed_parts=len(parts);db.commit()
    selected_id,selected_text=parts[1].id,parts[1].synthesis_text
    response=client.post(f'/audio/jobs/{job_id}/parts/{parts[1].part_index}/retry',headers=auth_headers)
    assert response.status_code==200,response.text
    calls=[];transport(monkeypatch,calls)
    monkeypatch.setenv('DOWNLOAD_PATH',str(tmp_path))
    audio.process_audio_job(job_id,sessionmaker(bind=db.get_bind()))
    db.expire_all();job=db.get(ChapterAudioJob,job_id)
    assert job.status=='completed' and job.completed_parts==len(parts)
    assert calls==[selected_text]
    for part in db.query(ChapterAudioPart).filter_by(job_id=job_id):
        if part.id==selected_id:
            assert part.duration_seconds==.1 and part.synthesis_text==selected_text
        else:
            assert (part.audio_path,Path(part.audio_path).read_bytes(),part.duration_seconds)==original[part.id]
    from app.services.audio_alignment import wav_duration
    assert wav_duration(job.audio_path)==pytest.approx(.2*(len(parts)-1)+.1)
