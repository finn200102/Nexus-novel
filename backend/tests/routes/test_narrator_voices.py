import base64
from contextlib import nullcontext
from datetime import timedelta
from unittest.mock import Mock

import httpx
from sqlalchemy.orm import sessionmaker
from app.models import VoiceProfile, User, Novel, Chapter, ChapterAudioJob
from app.services import voice_service, audio_job_service
from app.services.job_lease import claim, recover_expired, utcnow


def configure(monkeypatch, tmp_path):
    key = tmp_path / "voice-key"; key.write_text("test-key" * 8)
    monkeypatch.setenv("NEXUS_LOCAL_VOICE_URL", "http://host.docker.internal:8893")
    monkeypatch.setenv("NEXUS_LOCAL_VOICE_KEY_FILE", str(key))


def reference(db, user_id, **kwargs):
    voice = VoiceProfile(user_id=user_id, name="My narrator", language="German", sample=b"RIFF-reference", transcript="Original words", model=voice_service.MODEL, **kwargs)
    db.add(voice); db.commit(); db.refresh(voice)
    return voice


def test_upload_list_preview_and_account_isolation(client, auth_headers, db, test_user, monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    response = client.post("/audio/voices", headers=auth_headers, json={"name":"Narrator", "language":"German", "audio_base64":base64.b64encode(b"test recording").decode()})
    assert response.status_code == 202 and response.json()["status"] == "queued"
    assert "audio_base64" not in response.json() and "sample" not in response.json()
    profile_id = response.json()["id"]
    assert client.get("/audio/voices", headers=auth_headers).json()[0]["id"] == profile_id
    stranger = User(username="other-voice-owner", password="unused"); db.add(stranger); db.commit()
    other = reference(db, stranger.id, status="completed", preview=b"RIFF-private-preview")
    assert len(client.get("/audio/voices", headers=auth_headers).json()) == 1
    for method, path in (("get",f"/{other.id}/preview"),("post",f"/{other.id}/retry"),("delete",f"/{other.id}")):
        assert getattr(client, method)("/audio/voices" + path, headers=auth_headers).status_code == 404
    profile = db.get(VoiceProfile, profile_id);profile.preview=b"RIFF-preview";db.commit()
    result = client.get(f"/audio/voices/{profile_id}/preview", headers=auth_headers)
    assert result.content == b"RIFF-preview" and "no-store" in result.headers["cache-control"]


def test_reject_bad_uploads_and_remote_configuration(client, auth_headers, monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    for item in ({"name":"  ","audio_base64":"eA=="}, {"name":"N","audio_base64":"%%%%"}, {"name":"N","audio_base64":"eA==","language":"unsupported"}):
        assert client.post("/audio/voices", headers=auth_headers, json=item).status_code == 422
    monkeypatch.setenv("NEXUS_LOCAL_VOICE_URL", "https://external.example")
    assert not client.get("/audio/voices/capabilities", headers=auth_headers).json()["configured"]
    assert client.post("/audio/voices", headers=auth_headers, json={"name":"N","audio_base64":"eA=="}).status_code == 503


def test_preparation_uses_local_key_and_stores_ready_preview(db, test_user, monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    voice = reference(db, test_user.id)
    posted = []
    class Client:
        def __init__(self, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def post(self, url, *, json, headers):
            posted.append((url,json,headers))
            return httpx.Response(200, request=httpx.Request("POST",url), json={"model":voice_service.MODEL,"audio_base64":base64.b64encode(b"RIFF-normalized").decode(),"preview_base64":base64.b64encode(b"RIFF-preview").decode(),"transcript":"Prepared words"})
    monkeypatch.setattr(voice_service.httpx, "Client", Client)
    monkeypatch.setattr(voice_service, "heartbeat", lambda *args: nullcontext())
    voice_service.prepare_voice(voice.id, sessionmaker(bind=db.get_bind()))
    db.expire_all();db.refresh(voice)
    assert voice.status == "completed" and voice.sample == b"RIFF-normalized" and voice.preview == b"RIFF-preview"
    assert voice.transcript == "Prepared words" and voice.lease_owner is None
    assert posted[0][0] == "http://host.docker.internal:8893/v1/voices/prepare"
    assert posted[0][1]["language"] == "German" and posted[0][2]["Authorization"].startswith("Bearer ")


def test_interrupted_preparation_has_one_owner_and_recovers(db, test_user):
    voice = reference(db, test_user.id)
    assert claim(db, VoiceProfile, voice.id, worker_id="one") is not None
    assert claim(db, VoiceProfile, voice.id, worker_id="two") is None
    voice.lease_expires_at = utcnow() - timedelta(seconds=1);db.commit()
    assert recover_expired(db, VoiceProfile) == 1
    assert claim(db, VoiceProfile, voice.id, worker_id="two").attempt_count == 2


def test_deleting_narrator_cancels_pending_jobs_but_keeps_finished_audio(client, auth_headers, db, test_user, test_library):
    voice = reference(db, test_user.id, status="completed", preview=b"RIFF-preview")
    novel=Novel(title="Story",library_id=test_library.id);db.add(novel);db.flush()
    chapter=Chapter(novel_id=novel.id,chapter_number=1,content="Read me");db.add(chapter);db.flush()
    for status in ("queued","completed"):
        db.add(ChapterAudioJob(user_id=test_user.id,library_id=test_library.id,novel_id=novel.id,chapter_id=chapter.id,voice_profile_id=voice.id,status=status,provider_id="qwen3_clone",provider_url="local",provider_model="m",provider_voice="My narrator",audio_path="finished.wav" if status=="completed" else None))
    db.commit()
    assert client.delete(f"/audio/voices/{voice.id}",headers=auth_headers).status_code == 204
    db.expire_all()
    assert db.get(VoiceProfile,voice.id) is None
    jobs=db.query(ChapterAudioJob).order_by(ChapterAudioJob.id).all()
    assert [j.status for j in jobs] == ["cancelled","completed"]
    assert all(j.voice_profile_id is None for j in jobs) and jobs[1].audio_path == "finished.wav"


def test_clone_job_uses_owned_profile_and_ignores_client_endpoint(client, auth_headers, db, test_user, test_library, monkeypatch, tmp_path):
    configure(monkeypatch,tmp_path)
    voice=reference(db,test_user.id,status="completed")
    novel=Novel(title="Story",library_id=test_library.id);db.add(novel);db.flush()
    chapter=Chapter(novel_id=novel.id,chapter_number=1,title="Title",content="Long sentence " * 90);db.add(chapter);db.commit()
    body={"library_id":test_library.id,"novel_id":novel.id,"chapter_number":1,"voice_profile_id":voice.id,"provider":{"id":"custom","base_url":"https://unwanted.example","model":"wrong","voice":"wrong"}}
    result=client.post("/audio/jobs",headers=auth_headers,json=body)
    assert result.status_code == 202
    job=db.get(ChapterAudioJob,result.json()["id"])
    assert job.provider_url == "http://host.docker.internal:8893/v1" and job.provider_model == voice_service.MODEL
    assert job.provider_id == "qwen3_clone" and job.provider_voice == voice.name
    from app.models.audio_job import ChapterAudioPart
    assert max(len(p.text) for p in db.query(ChapterAudioPart).all()) <= 350
    other=User(username="stranger",password="unused");db.add(other);db.commit()
    not_owned=reference(db,other.id,status="completed")
    body["voice_profile_id"]=not_owned.id
    assert client.post("/audio/jobs",headers=auth_headers,json=body).status_code == 422


def test_long_sentence_after_title_stays_inside_provider_limit():
    parts=audio_job_service.split_text("Short title. " + "a"*1400 + ". Final words.",350)
    assert max(map(len,parts)) <= 350 and "".join(parts).count("a") == 1401


def test_default_narrator_is_private_revisioned_and_cleared_on_removal(client, auth_headers, db, test_user):
    first = reference(db, test_user.id, status="completed")
    second = reference(db, test_user.id, status="completed")
    pending = reference(db, test_user.id, status="queued")
    stranger = User(username="default-narrator-stranger", password="unused")
    db.add(stranger); db.commit()
    foreign = reference(db, stranger.id, status="completed")
    route = "/audio/voices/default"
    assert client.get(route, headers=auth_headers).json() == {"voice_profile_id": None, "revision": 0}
    def choose(profile_id, revision):
        return client.put(route, headers=auth_headers, json={"voice_profile_id": profile_id, "expected_revision": revision})
    assert choose(foreign.id, 0).status_code == 404
    assert choose(pending.id, 0).status_code == 409
    saved = choose(first.id, 0)
    assert saved.json() == {"voice_profile_id": first.id, "revision": 1}
    assert choose(first.id, 0).json() == saved.json()
    stale = choose(second.id, 0)
    assert stale.status_code == 409 and stale.json()["detail"]["current"] == saved.json()
    assert client.get(route, headers=auth_headers).json() == saved.json()
    assert choose(second.id, 1).json() == {"voice_profile_id": second.id, "revision": 2}
    assert client.delete(f"/audio/voices/{first.id}", headers=auth_headers).status_code == 204
    assert client.get(route, headers=auth_headers).json()["voice_profile_id"] == second.id
    assert client.delete(f"/audio/voices/{second.id}", headers=auth_headers).status_code == 204
    assert client.get(route, headers=auth_headers).json() == {"voice_profile_id": None, "revision": 3}
    from app.models.reader_preference import ReaderPreference
    assert db.query(ReaderPreference).filter_by(user_id=stranger.id, scope="audio").count() == 0


def test_upload_excerpt_selection_is_bounded_and_persisted(client,auth_headers,db,test_user,monkeypatch,tmp_path):
    configure(monkeypatch,tmp_path)
    body={'name':'Selected narrator','audio_base64':base64.b64encode(b'original long recording').decode(),
          'excerpt_start_seconds':35.5,'excerpt_duration_seconds':15}
    result=client.post('/audio/voices',headers=auth_headers,json=body)
    assert result.status_code==202
    profile=db.get(VoiceProfile,result.json()['id'])
    assert profile.excerpt_start_seconds==35.5 and profile.excerpt_duration_seconds==15
    assert profile.sample==b'original long recording'
    payload=voice_service.request_payload(profile,prepare=True)
    assert payload['excerpt_start_seconds']==35.5 and payload['excerpt_duration_seconds']==15
    assert 'excerpt_start_seconds' not in voice_service.request_payload(profile,input='Narrate prepared audio')
    for selection in ({'excerpt_start_seconds':0}, {'excerpt_duration_seconds':15},
                      {'excerpt_start_seconds':-1,'excerpt_duration_seconds':15},
                      {'excerpt_start_seconds':3601,'excerpt_duration_seconds':15},
                      {'excerpt_start_seconds':0,'excerpt_duration_seconds':2.99},
                      {'excerpt_start_seconds':0,'excerpt_duration_seconds':30.01}):
        invalid={k:v for k,v in body.items() if not k.startswith('excerpt_')};invalid.update(selection)
        assert client.post('/audio/voices',headers=auth_headers,json=invalid).status_code==422


def test_preparation_sends_excerpt_once_and_keeps_only_safe_failure_details(db,test_user,monkeypatch,tmp_path):
    configure(monkeypatch,tmp_path)
    profile=reference(db,test_user.id,excerpt_start_seconds=35,excerpt_duration_seconds=15)
    posted=[]
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,*,json,headers):
            posted.append(json)
            return httpx.Response(422,request=httpx.Request('POST',url),json={'detail':self.detail})
    monkeypatch.setattr(voice_service.httpx,'Client',Client)
    monkeypatch.setattr(voice_service,'heartbeat',lambda *args:nullcontext())
    safe='Audio could not be decoded. Try a WAV, MP3, M4A, Ogg or FLAC recording.'
    Client.detail=safe
    voice_service.prepare_voice(profile.id,sessionmaker(bind=db.get_bind()))
    db.expire_all();db.refresh(profile)
    assert profile.status=='failed' and profile.error==safe
    assert profile.excerpt_start_seconds==35 and profile.sample==b'RIFF-reference'
    assert posted[0]['excerpt_start_seconds']==35 and posted[0]['excerpt_duration_seconds']==15
    profile.status='queued';profile.next_attempt_at=None;db.commit()
    Client.detail='Private recording words and secret provider path'
    voice_service.prepare_voice(profile.id,sessionmaker(bind=db.get_bind()))
    db.expire_all();db.refresh(profile)
    assert profile.status=='failed' and 'Private recording' not in profile.error
    assert 'secret' not in profile.error
    assert posted[1]['excerpt_start_seconds']==35


def test_excerpt_migration_preserves_0036_voices_and_default(tmp_path):
    import json
    import os
    from alembic import command
    from sqlalchemy import create_engine, text
    from app.db_migrations import alembic_config
    urls=[f"sqlite:///{tmp_path / 'narrator-upgrade.db'}"]
    if os.getenv('NEXUS_TEST_POSTGRES_URL'):
        urls.append(os.environ['NEXUS_TEST_POSTGRES_URL'])
    for url in urls:
        engine=create_engine(url)
        try:
            with engine.begin() as connection:
                if engine.dialect.name=='postgresql':
                    connection.execute(text('DROP SCHEMA public CASCADE'))
                    connection.execute(text('CREATE SCHEMA public'))
                config=alembic_config(connection)
                command.upgrade(config,'0036')
                connection.execute(text("INSERT INTO users (id,username,password,storage_id) VALUES (1,'voice-owner','unused','00000000-0000-4000-8000-000000000001')"))
                connection.execute(text("INSERT INTO voice_profiles (id,user_id,name,language,sample,transcript,preview,model,status) VALUES (1,1,'Existing narrator','English',:sample,'Existing private transcript',:preview,'fixture','completed')"),{'sample':b'RIFF-old-reference','preview':b'RIFF-old-preview'})
                connection.execute(text('INSERT INTO reader_preferences (user_id,scope,revision,"values") VALUES (1,\'audio\',5,:value)'),{'value':json.dumps({'voice_profile_id':1})})
                command.upgrade(config,'0037')
                row=connection.execute(text('SELECT sample,transcript,preview,status,excerpt_start_seconds,excerpt_duration_seconds FROM voice_profiles WHERE id=1')).one()
                assert bytes(row[0])==b'RIFF-old-reference' and row[1]=='Existing private transcript'
                assert bytes(row[2])==b'RIFF-old-preview' and tuple(row[3:])==('completed',None,None)
                preference=connection.execute(text('SELECT revision,"values" FROM reader_preferences WHERE user_id=1 AND scope=\'audio\'')).one()
                values=json.loads(preference[1]) if isinstance(preference[1],str) else preference[1]
                assert preference[0]==5 and values=={'voice_profile_id':1}
                connection.execute(text('UPDATE voice_profiles SET excerpt_start_seconds=35.5,excerpt_duration_seconds=15 WHERE id=1'))
                command.upgrade(config,'head')
                assert connection.execute(text('SELECT excerpt_start_seconds,excerpt_duration_seconds FROM voice_profiles WHERE id=1')).one()==(35.5,15)
                command.downgrade(config,'0036')
                assert connection.execute(text('SELECT transcript FROM voice_profiles WHERE id=1')).scalar_one()=='Existing private transcript'
        finally:
            engine.dispose()
