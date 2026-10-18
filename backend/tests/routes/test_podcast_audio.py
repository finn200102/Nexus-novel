from datetime import timedelta
from sqlalchemy.orm import sessionmaker

from app.models import ChapterAudioJob,User
from app.models.podcast_audio import PodcastAudioJob
from app.services import podcast_audio_service as audio
from app.services import podcast_service
from app.services.job_lease import claim,recover_expired,utcnow
from tests.routes.test_podcasts import fixture,prepare


def enable(client,headers,novel):
    return client.post(f'/audio/stories/{novel.id}/podcast',headers=headers)


def test_conversion_requires_explicit_feed_activation_and_never_queues_speech(client,auth_headers,db,test_user,test_library,tmp_path,monkeypatch):
    novel,source,path=fixture(db,test_user,test_library,tmp_path,monkeypatch)
    factory=sessionmaker(bind=db.get_bind())
    audio.process_due_podcast_audio(factory)
    assert db.query(PodcastAudioJob).count()==0 and db.query(ChapterAudioJob).count()==1
    first=enable(client,auth_headers,novel)
    assert first.status_code==201 and first.json()['pending']==1 and first.json()['format']=='mp3'
    assert first.json()['episodes'][0]['source_audio_job_id']==source.id
    token=first.json()['feed_url'].split('/podcasts/')[1].split('/')[0]
    for _ in range(3):
        assert client.get(first.json()['feed_url']).status_code==200
        assert client.head(first.json()['feed_url']).status_code==200
    assert db.query(PodcastAudioJob).count()==1 and db.query(PodcastAudioJob).one().status=='queued'
    assert not list(tmp_path.rglob('*.mp3'))
    second=enable(client,auth_headers,novel)
    assert second.status_code==201 and db.query(PodcastAudioJob).count()==1
    job=db.query(PodcastAudioJob).one()
    assert token not in str(job.source_snapshot)
    audio.process_due_podcast_audio(factory)
    db.expire_all();db.refresh(job)
    assert job.status=='completed' and job.audio_bytes>0
    assert job.source_snapshot['file']['sha256']
    assert audio.podcast_audio_storage_bytes(test_user.id)>=job.audio_bytes
    assert path.exists() and db.query(ChapterAudioJob).count()==1


def test_active_feed_discovers_later_completed_recordings_only_once(client,auth_headers,db,test_user,test_library,tmp_path,monkeypatch):
    novel,source,path=fixture(db,test_user,test_library,tmp_path,monkeypatch)
    enable(client,auth_headers,novel);prepare(db)
    later=ChapterAudioJob(user_id=test_user.id,library_id=test_library.id,novel_id=novel.id,chapter_id=source.chapter_id,
        chapter_key=source.chapter_key,manifest_epoch=source.manifest_epoch,manifest_revision=source.manifest_revision,
        status='processing',provider_id='local',provider_url='unused',provider_model='fixture',provider_voice='another',audio_path=str(path),audio_bytes=path.stat().st_size)
    db.add(later);db.commit()
    assert audio.discover(db)==0
    later.status='completed';db.commit()
    assert audio.discover(db)==1 and audio.discover(db)==0
    assert db.query(PodcastAudioJob).count()==2
    job=db.query(PodcastAudioJob).filter_by(source_audio_job_id=later.id).one()
    audio.process_job(job.id,sessionmaker(bind=db.get_bind()))
    db.expire_all()
    status=client.get(f'/audio/stories/{novel.id}/podcast',headers=auth_headers).json()
    assert status['ready']==1 and status['pending']==0 and status['episodes'][0]['source_audio_job_id']==later.id


def test_revocation_during_conversion_discards_output_and_reactivation_reuses_job(client,auth_headers,db,test_user,test_library,tmp_path,monkeypatch):
    novel,source,path=fixture(db,test_user,test_library,tmp_path,monkeypatch)
    result=enable(client,auth_headers,novel).json();job=db.query(PodcastAudioJob).one()
    old_feed=result['feed_url']
    def encode(fd,output,worker_db,job_id,owner,deadline,should_stop):
        output.write_bytes(b'not published')
        assert client.delete(f'/audio/stories/{novel.id}/podcast',headers=auth_headers).status_code==204
    monkeypatch.setattr(audio,'_encode',encode)
    audio.process_job(job.id,sessionmaker(bind=db.get_bind()))
    db.expire_all();db.refresh(job)
    assert job.status=='cancelled' and job.audio_path is None
    assert not list(tmp_path.rglob('*.mp3')) and path.exists()
    assert client.get(old_feed).status_code==404 and client.head(old_feed).status_code==404
    assert enable(client,auth_headers,novel).status_code==201
    assert db.query(PodcastAudioJob).count()==1
    db.refresh(job);assert job.status=='queued'


def test_invalid_recording_and_retry_are_owner_scoped(client,auth_headers,db,test_user,test_library,tmp_path,monkeypatch):
    novel,source,path=fixture(db,test_user,test_library,tmp_path,monkeypatch)
    path.write_bytes(b'RIFF-invalid')
    enable(client,auth_headers,novel);job=db.query(PodcastAudioJob).one()
    audio.process_job(job.id,sessionmaker(bind=db.get_bind()))
    db.expire_all();db.refresh(job)
    assert job.status=='failed' and job.error_code=='invalid_audio'
    status=client.get(f'/audio/stories/{novel.id}/podcast',headers=auth_headers).json()
    assert status['failed']==1 and status['episodes'][0]['id']==job.id
    endpoint=f'/audio/stories/{novel.id}/podcast/episodes/{job.id}/retry'
    other=User(username='other-podcast-episode-owner',password='unused');db.add(other);db.commit()
    job.user_id=other.id;db.commit()
    assert client.post(endpoint,headers=auth_headers).status_code==404
    job.user_id=test_user.id;db.commit()
    retried=client.post(endpoint,headers=auth_headers)
    assert retried.status_code==200 and retried.json()['status']=='queued'
    assert client.delete(f'/audio/stories/{novel.id}/podcast',headers=auth_headers).status_code==204
    assert client.post(endpoint,headers=auth_headers).status_code==409


def test_conversion_lease_recovery_and_changed_source_are_safe(client,auth_headers,db,test_user,test_library,tmp_path,monkeypatch):
    novel,source,path=fixture(db,test_user,test_library,tmp_path,monkeypatch)
    enable(client,auth_headers,novel);job=db.query(PodcastAudioJob).one()
    assert claim(db,PodcastAudioJob,job.id,worker_id='first') is not None
    assert claim(db,PodcastAudioJob,job.id,worker_id='second') is None
    job.lease_expires_at=utcnow()-timedelta(seconds=1);db.commit()
    assert recover_expired(db,PodcastAudioJob)==1
    job.next_attempt_at=None;db.commit()
    original_encode=audio._encode
    def interrupted(fd,output,worker_db,job_id,owner,deadline,should_stop):
        raise audio.ExportError('worker_stopped','Interrupted conversion; original recording preserved.')
    monkeypatch.setattr(audio,'_encode',interrupted)
    audio.process_job(job.id,sessionmaker(bind=db.get_bind()))
    db.expire_all();db.refresh(job)
    assert job.status=='retry_wait' and job.source_snapshot['file']['sha256']
    data=bytearray(path.read_bytes());data[-1]^=1;path.write_bytes(data)
    job.next_attempt_at=None;db.commit()
    monkeypatch.setattr(audio,'_encode',original_encode)
    audio.process_job(job.id,sessionmaker(bind=db.get_bind()))
    db.expire_all();db.refresh(job)
    assert job.status=='failed' and job.error_code=='source_changed'
    assert job.audio_path is None and path.exists()


def test_source_deletion_hook_cancels_derivatives_and_keeps_no_private_files(client,auth_headers,db,test_user,test_library,tmp_path,monkeypatch):
    novel,source,path=fixture(db,test_user,test_library,tmp_path,monkeypatch)
    enable(client,auth_headers,novel);prepare(db)
    assert audio.podcast_audio_storage_bytes(test_user.id)>0
    audio.delete_podcast_audio_for_source(db,source);db.commit()
    assert db.query(PodcastAudioJob).count()==0 and audio.podcast_audio_storage_bytes(test_user.id)==0
    assert path.exists()


def test_public_source_job_deletion_removes_podcast_cache(client,auth_headers,db,test_user,test_library,tmp_path,monkeypatch):
    from app.services.audio_job_service import delete_audio_job
    novel,source,path=fixture(db,test_user,test_library,tmp_path,monkeypatch)
    enable(client,auth_headers,novel);prepare(db)
    assert audio.podcast_audio_storage_bytes(test_user.id)>0
    delete_audio_job(db,source)
    assert db.query(PodcastAudioJob).count()==0 and db.query(ChapterAudioJob).count()==0
    assert audio.podcast_audio_storage_bytes(test_user.id)==0 and not path.exists()


def test_superseded_recording_does_not_waste_conversion_or_reactivate_old_jobs(client,auth_headers,db,test_user,test_library,tmp_path,monkeypatch):
    novel,source,path=fixture(db,test_user,test_library,tmp_path,monkeypatch)
    enable(client,auth_headers,novel);old=db.query(PodcastAudioJob).one()
    newer=ChapterAudioJob(user_id=test_user.id,library_id=test_library.id,novel_id=novel.id,chapter_id=source.chapter_id,
        chapter_key=source.chapter_key,manifest_epoch=source.manifest_epoch,manifest_revision=source.manifest_revision,
        status='completed',provider_id='local',provider_url='unused',provider_model='fixture',provider_voice='newer',audio_path=str(path),audio_bytes=path.stat().st_size)
    db.add(newer);db.commit()
    audio.process_job(old.id,sessionmaker(bind=db.get_bind()))
    db.expire_all();db.refresh(old)
    assert old.status=='cancelled' and old.audio_path is None
    enable(client,auth_headers,novel)
    db.refresh(old);assert old.status=='cancelled'
    audio.process_due_podcast_audio(sessionmaker(bind=db.get_bind()))
    db.expire_all()
    current=db.query(PodcastAudioJob).filter_by(source_audio_job_id=newer.id).one()
    assert current.status=='completed' and db.query(PodcastAudioJob).count()==2


def test_status_pages_late_failures_without_queueing_conversion(client,auth_headers,db,test_user,test_library,tmp_path,monkeypatch):
    from app.models import Chapter
    novel,source,path=fixture(db,test_user,test_library,tmp_path,monkeypatch)
    for number in range(2,206):
        chapter=Chapter(novel_id=novel.id,chapter_number=number,title=f'Chapter {number}')
        db.add(chapter);db.flush()
        job=ChapterAudioJob(user_id=test_user.id,library_id=test_library.id,novel_id=novel.id,
            chapter_id=chapter.id,status='completed',provider_id='local',provider_url='unused',
            provider_model='fixture',provider_voice='fixture',audio_path=str(path),audio_bytes=path.stat().st_size)
        from app.services.chapter_identity_service import identity
        db.refresh(chapter)
        captured=identity(chapter)
        job.chapter_key=captured['chapter_key'];job.manifest_epoch=captured['manifest_epoch'];job.manifest_revision=captured['manifest_revision']
        db.add(job);db.flush()
        if number==205:
            db.add(PodcastAudioJob(user_id=test_user.id,novel_id=novel.id,source_audio_job_id=job.id,
                chapter_number=number,pipeline_version=audio.PIPELINE,source_snapshot={},status='failed',
                error_code='fixture_failure',error='Retry this episode.'))
    db.commit()
    enable(client,auth_headers,novel)
    before=db.query(PodcastAudioJob).count()
    endpoint=f'/audio/stories/{novel.id}/podcast'
    first=client.get(endpoint,headers=auth_headers).json()
    last=client.get(endpoint+'?offset=200&limit=50',headers=auth_headers).json()
    assert first['episodes_total']==205 and len(first['episodes'])==50
    assert first['pending']==204 and first['failed']==1 and first['episodes_offset']==0
    assert last['episodes_total']==205 and last['episodes_offset']==200 and last['episodes_limit']==50
    assert [item['chapter_number'] for item in last['episodes']]==list(range(201,206))
    failed=last['episodes'][-1]
    assert failed['status']=='failed' and failed['id'] is not None
    assert db.query(PodcastAudioJob).count()==before
    assert client.get(endpoint+'?limit=201',headers=auth_headers).status_code==422
    retry=client.post(endpoint+f"/episodes/{failed['id']}/retry",headers=auth_headers)
    assert retry.status_code==200 and retry.json()['status']=='queued'


def test_private_storage_rejects_linked_ancestors_and_traversal(db,test_user,test_library,tmp_path,monkeypatch):
    import pytest
    import shutil
    novel,source,path=fixture(db,test_user,test_library,tmp_path,monkeypatch)
    external=tmp_path/'outside';external.mkdir()
    shutil.move(str(tmp_path/'audio'),str(external/'audio'))
    (tmp_path/'audio').symlink_to(external/'audio',target_is_directory=True)
    assert podcast_service.audio_path(source) is None
    output=external/'podcasts'/str(test_user.id)/'123'/'episode.mp3'
    output.parent.mkdir(parents=True);output.write_bytes(b'private')
    (tmp_path/'podcast-audio').symlink_to(external/'podcasts',target_is_directory=True)
    with pytest.raises(audio.ExportError):audio.private_path(tmp_path/'podcast-audio'/str(test_user.id)/'123'/'episode.mp3',test_user.id,123)
    (tmp_path/'podcast-audio').unlink()
    with pytest.raises(audio.ExportError):audio.private_path(tmp_path/'podcast-audio'/str(test_user.id)/'123'/'..'/'..'/'..'/'outside'/'secret',test_user.id,123,required=False)


def test_archived_episode_keeps_private_media_but_never_attaches_to_reused_number(client,auth_headers,db,test_user,test_library,tmp_path,monkeypatch):
    from app.models import Chapter
    from xml.etree import ElementTree as ET
    novel,source,path=fixture(db,test_user,test_library,tmp_path,monkeypatch)
    response=enable(client,auth_headers,novel).json();prepare(db)
    derivative=db.query(PodcastAudioJob).one();original=derivative.source_snapshot.copy()
    chapter=db.get(Chapter,source.chapter_id);chapter.archived=True;db.commit()
    db.add(Chapter(novel_id=novel.id,chapter_number=1,title='Different replacement chapter'));db.commit()
    status=client.get(f'/audio/stories/{novel.id}/podcast',headers=auth_headers).json()
    assert status['episodes_total']==0 and audio.discover(db)==0
    feed=client.get(response['feed_url'])
    assert ET.fromstring(feed.content).find('channel/item') is None
    token=response['feed_url'].split('/podcasts/')[1].split('/')[0]
    old=client.get(f'/podcasts/{token}/audio/{source.id}.mp3',headers={'Range':'bytes=0-3'})
    assert old.status_code==206 and len(old.content)==4
    db.refresh(derivative);assert derivative.source_snapshot==original


def test_podcast_original_markers_stay_immutable_when_same_uuid_is_renumbered(client,auth_headers,db,test_user,test_library,tmp_path,monkeypatch):
    from app.models import Chapter
    from xml.etree import ElementTree as ET
    novel,source,path=fixture(db,test_user,test_library,tmp_path,monkeypatch)
    response=enable(client,auth_headers,novel).json();prepare(db)
    chapter=db.get(Chapter,source.chapter_id);chapter.chapter_number=-2;chapter.title='New display title';db.commit()
    status=client.get(f'/audio/stories/{novel.id}/podcast',headers=auth_headers).json()
    assert status['episodes'][0]['chapter_number']==-2
    assert status['episodes'][0]['chapter_key']==source.chapter_key
    item=ET.fromstring(client.get(response['feed_url']).content).find('channel/item')
    assert item.findtext('title')=='One & two'
    assert item.findtext('description')=='Chapter 1'
