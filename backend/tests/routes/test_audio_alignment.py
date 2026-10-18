import io
import wave
from sqlalchemy.orm import sessionmaker
import httpx
import pytest
from contextlib import nullcontext
from app.models import Chapter, Novel, ChapterAudioJob, ChapterAudioPart, ChapterVersion, User
from app.services.chapter_document import from_html
from app.services.audio_alignment import chunks, plan_passages, wav_duration, manifest
from app.services import audio_job_service


def audio(seconds=1):
    out=io.BytesIO()
    with wave.open(out,"wb") as f:
        f.setnchannels(1);f.setsampwidth(2);f.setframerate(24000);f.writeframes(b"\x00\x00" * int(24000*seconds))
    return out.getvalue()


def story(db, library):
    novel=Novel(title="Aligned",library_id=library.id);db.add(novel);db.flush()
    doc=from_html('<p>😀 First   passage.</p><aside class="author-note"><p>Skip this note.</p></aside><p>Another passage.</p>')
    chapter=Chapter(novel_id=novel.id,chapter_number=1,title="Spoken title",content=doc["plain_text"],document=doc)
    db.add(chapter);db.commit();return chapter


def queue(db,user,library,chapter,**kwargs):
    return audio_job_service.queue_audio_job(db,user_id=user.id,library_id=library.id,novel_id=chapter.novel_id,chapter=chapter,provider={"id":"custom","base_url":"http://provider/v1","model":"fixture","voice":"test"},**kwargs)


def test_passages_keep_exact_unicode_offsets_and_skip_notes():
    doc=from_html('<p>😀 Alpha   beta gamma delta.</p><aside class="author-note"><p>Secret note.</p></aside>')
    parts=plan_passages(doc,"Title",8)
    assert parts[0]["block_id"] is None
    assert all(len(p["text"])<=8 for p in parts)
    text=doc["blocks"][0]["text"]
    for p in parts[1:]:
        source=text.encode("utf-16-le")[p["text_offset"]*2:(p["text_offset"]+p["text_length"])*2].decode("utf-16-le")
        assert " ".join(source.split()) == p["text"]
    assert not any("Secret" in p["text"] for p in parts)
    assert any("Secret" in p["text"] for p in plan_passages(doc,"",100,include_author_notes=True))


def test_normalizing_chunks_preserves_all_nonwhitespace_text():
    raw="  😀 begin\n\n"+"中"*103+"   end. "
    result=list(chunks(raw,20))
    assert "".join("".join(x[0].split()) for x in result)=="".join(raw.split())
    assert all(0<=start<end<=len(raw) and len(spoken)<=20 for spoken,start,end in result)


def test_new_job_retains_source_and_never_relabels_existing_job(db,test_user,test_library):
    chapter=story(db,test_library);job=queue(db,test_user,test_library,chapter)
    old=job.source_version
    assert old == chapter.document["content_version"] and not job.include_author_notes
    retained=db.query(ChapterVersion).filter_by(chapter_id=chapter.id,content_version=old).one()
    assert retained.document==chapter.document
    parts=db.query(ChapterAudioPart).filter_by(job_id=job.id).all()
    assert len(parts)==3 and parts[0].block_id is None and parts[1].text_offset==0
    assert all("Skip this note" not in p.text for p in parts)
    chapter.document=from_html("<p>Revised future text.</p>");db.commit()
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as conflict:
        queue(db,test_user,test_library,chapter)
    assert conflict.value.status_code==409
    assert job.source_version==old  # the old request is retained rather than rebound to revised text


def test_processing_measures_real_segments_and_manifest_is_private(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    chapter=story(db,test_library);job=queue(db,test_user,test_library,chapter)
    monkeypatch.setenv("DOWNLOAD_PATH",str(tmp_path))
    class Client:
        def __init__(self,**kw):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):return httpx.Response(200,request=httpx.Request("POST",url),content=audio(.5))
    monkeypatch.setattr(audio_job_service.httpx,"Client",Client)
    monkeypatch.setattr(audio_job_service,"heartbeat",lambda *args:nullcontext())
    audio_job_service.process_audio_job(job.id,sessionmaker(bind=db.get_bind()))
    db.expire_all();db.refresh(job)
    assert job.status=="completed"
    result=client.get(f"/audio/jobs/{job.id}/manifest",headers=auth_headers)
    assert result.status_code==200
    data=result.json();assert data["precision"]=="segment" and data["current_source"]
    assert data["duration_seconds"]==1.5 and len(data["segments"])==3
    assert data["segments"][1]["start_seconds"]==.5 and data["segments"][1]["block_id"]==chapter.document["blocks"][0]["id"]
    other=User(username="private-audio-owner",password="unused");db.add(other);db.commit()
    stranger=ChapterAudioJob(user_id=other.id,library_id=test_library.id,novel_id=chapter.novel_id,chapter_id=chapter.id,status="completed",provider_id="p",provider_url="local",provider_model="m",provider_voice="v")
    db.add(stranger);db.commit()
    assert client.get(f"/audio/jobs/{stranger.id}/manifest",headers=auth_headers).status_code==404
    chapter.document=from_html("<p>Revised unseen prose.</p>");db.commit()
    changed=client.get(f"/audio/jobs/{job.id}/manifest",headers=auth_headers).json()
    assert changed["source_version"]==data["source_version"] and not changed["current_source"]


def test_legacy_jobs_stay_playable_without_fabricated_alignment(db,test_user,test_library,tmp_path):
    chapter=story(db,test_library);path=tmp_path/"old.wav";path.write_bytes(audio())
    job=ChapterAudioJob(user_id=test_user.id,library_id=test_library.id,novel_id=chapter.novel_id,chapter_id=chapter.id,status="completed",audio_path=str(path),provider_id="p",provider_url="local",provider_model="m",provider_voice="v",total_parts=1)
    db.add(job);db.flush();db.add(ChapterAudioPart(job_id=job.id,part_index=0,text="Older words",status="completed",audio_path=str(path)));db.commit()
    result=manifest(db,job)
    assert result["precision"]=="unavailable" and result["segments"]==[] and result["source_version"] is None
    assert path.read_bytes()==audio()


def test_truncated_audio_cannot_receive_a_valid_duration(tmp_path):
    path=tmp_path/"truncated.wav";path.write_bytes(audio()[:-100])
    with pytest.raises(ValueError,match="truncated"):wav_duration(path)


def test_incomplete_part_sequence_cannot_claim_alignment(db,test_user,test_library,tmp_path):
    chapter=story(db,test_library);job=queue(db,test_user,test_library,chapter)
    path=tmp_path/"narration.wav";path.write_bytes(audio())
    job.status="completed";job.audio_path=str(path)
    parts=db.query(ChapterAudioPart).filter_by(job_id=job.id).order_by(ChapterAudioPart.part_index).all()
    for part in parts:
        part.status="completed";part.duration_seconds=1
    parts[-1].part_index=job.total_parts+1
    db.commit()
    result=manifest(db,job)
    assert result["precision"]=="unavailable" and result["segments"]==[]
    assert result["duration_seconds"] is None


def test_alignment_upgrade_preserves_existing_narration(tmp_path):
    from alembic import command
    from sqlalchemy import create_engine, text
    from app.db_migrations import alembic_config

    engine=create_engine(f"sqlite:///{tmp_path / 'audio-upgrade.db'}")
    try:
        with engine.begin() as connection:
            config=alembic_config(connection)
            command.upgrade(config,"0035")
            connection.execute(text("INSERT INTO users (id,username,password,storage_id) VALUES (1,'reader','unused','00000000-0000-4000-8000-000000000001')"))
            connection.execute(text("INSERT INTO libraries (id,user_id,name) VALUES (1,1,'Books')"))
            connection.execute(text("INSERT INTO novels (id,library_id,title) VALUES (1,1,'Story')"))
            connection.execute(text("INSERT INTO chapters (id,novel_id,chapter_number,title,content_status,audio_status,retry_count) VALUES (1,1,1,'Chapter','PRESENT','PRESENT',0)"))
            connection.execute(text("INSERT INTO chapter_audio_jobs (id,user_id,library_id,novel_id,chapter_id,status,provider_id,provider_url,provider_model,provider_voice,audio_path,total_parts) VALUES (1,1,1,1,1,'completed','custom','http://local/v1','fixture','reader','/private/narration.wav',1)"))
            connection.execute(text("INSERT INTO chapter_audio_parts (job_id,part_index,text,status,audio_path) VALUES (1,0,'Retained words','completed','/private/part.wav')"))
            command.upgrade(config,"0036")
            assert connection.execute(text("SELECT audio_path,source_version,include_author_notes FROM chapter_audio_jobs WHERE id=1")).one()==('/private/narration.wav',None,None)
            assert connection.execute(text("SELECT text,audio_path,block_id,text_offset,text_length,duration_seconds FROM chapter_audio_parts WHERE job_id=1")).one()==('Retained words','/private/part.wav',None,None,None,None)
            command.downgrade(config,"0035")
            assert connection.execute(text("SELECT text,audio_path FROM chapter_audio_parts WHERE job_id=1")).one()==('Retained words','/private/part.wav')
    finally:
        engine.dispose()


def test_deleted_inflight_job_discards_provider_audio_without_recreating_files(db,test_user,test_library,monkeypatch,tmp_path):
    import shutil
    chapter=story(db,test_library);job=queue(db,test_user,test_library,chapter)
    job_id=job.id
    factory=sessionmaker(bind=db.get_bind())
    monkeypatch.setenv("DOWNLOAD_PATH",str(tmp_path))
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,**kwargs):
            with factory() as deleting:
                deleting.query(ChapterAudioPart).filter_by(job_id=job_id).delete()
                deleting.query(ChapterAudioJob).filter_by(id=job_id).delete()
                deleting.commit()
            shutil.rmtree(tmp_path / "audio")
            return httpx.Response(200,request=httpx.Request("POST",url),content=audio(.5))
    monkeypatch.setattr(audio_job_service.httpx,"Client",Client)
    monkeypatch.setattr(audio_job_service,"heartbeat",lambda *args:nullcontext())
    audio_job_service.process_audio_job(job_id,factory)
    db.expire_all()
    assert db.query(ChapterAudioJob).filter_by(id=job_id).first() is None
    assert not (tmp_path / "audio").exists()
    assert not list(tmp_path.rglob("*.wav"))
