from xml.etree import ElementTree as ET
import io
import wave
from contextlib import nullcontext
from sqlalchemy.orm import sessionmaker

from app.models import Chapter, Novel, ChapterAudioJob
from app.models.podcast import PodcastFeedToken
from app.services import podcast_service
from app.services import podcast_audio_service
from app.models.podcast_audio import PodcastAudioJob
from config.settings import settings


def fixture(db, user, library, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, 'DOWNLOAD_PATH', str(tmp_path))
    novel = Novel(title='Story <&>\x01', library_id=library.id)
    db.add(novel); db.flush()
    chapter = Chapter(novel_id=novel.id, chapter_number=1, title='One & two')
    db.add(chapter); db.flush()
    folder=tmp_path/'audio'/str(user.id);folder.mkdir(parents=True)
    output=io.BytesIO()
    with wave.open(output,'wb') as recording:
        recording.setnchannels(1);recording.setsampwidth(2);recording.setframerate(24000)
        recording.writeframes(b'\x00\x01'*24000)
    path = folder/'recording.wav'; path.write_bytes(output.getvalue())
    monkeypatch.setattr(podcast_audio_service,'heartbeat',lambda *args:nullcontext())
    job = ChapterAudioJob(user_id=user.id,library_id=library.id,novel_id=novel.id,
        chapter_id=chapter.id,status='completed',provider_id='local',provider_url='http://localhost',
        provider_model='fixture',provider_voice='fixture',audio_path=str(path),audio_bytes=path.stat().st_size)
    from app.services.chapter_identity_service import identity
    db.refresh(chapter)
    captured=identity(chapter)
    job.chapter_key=captured['chapter_key'];job.manifest_epoch=captured['manifest_epoch'];job.manifest_revision=captured['manifest_revision']
    db.add(job); db.commit()
    return novel, job, path


def prepare(db):
    ids=[job.id for job in db.query(PodcastAudioJob).filter_by(status='queued')]
    for job_id in ids:podcast_audio_service.process_job(job_id,sessionmaker(bind=db.get_bind()))
    db.expire_all()
    assert all(job.status=='completed' for job in db.query(PodcastAudioJob)),[(job.status,job.error_code,job.error) for job in db.query(PodcastAudioJob)]


def test_private_feed_rotation_revocation_and_ranges(client, auth_headers, db, test_user, test_library, tmp_path, monkeypatch):
    novel, job, path = fixture(db,test_user,test_library,tmp_path,monkeypatch)
    endpoint=f'/audio/stories/{novel.id}/podcast'
    assert client.get(endpoint,headers=auth_headers).json()['active'] is False
    response=client.post(endpoint,headers={**auth_headers,'x-forwarded-prefix':'/api','x-forwarded-host':'192.168.1.2:8180'})
    assert response.status_code==201 and response.headers['cache-control']=='private, no-store'
    url=response.json()['feed_url']; assert url.startswith('http://192.168.1.2:8180/api/podcasts/')
    route=url.split('/api',1)[1]
    token=route.split('/')[2]
    row=db.query(PodcastFeedToken).one()
    assert row.token_hash==podcast_service.digest(token) and row.token_hash!=token
    status=client.get(endpoint,headers=auth_headers).json()
    assert status['active'] is True and status['feed_url'] is None and status['pending']==1
    assert ET.fromstring(client.get(route).content).find('channel/item') is None
    assert client.head(route).status_code==200
    assert db.query(PodcastAudioJob).count()==1
    prepare(db)
    feed=client.get(route); assert feed.status_code==200
    rss=ET.fromstring(feed.content)
    assert rss.findtext('channel/title')=='Story <&>'
    item=rss.find('channel/item'); assert item.findtext('title')=='One & two'
    guid=item.findtext('guid')
    audio=item.find('enclosure').attrib
    derivative=db.query(PodcastAudioJob).one()
    assert audio['length']==str(derivative.audio_bytes) and audio['type']=='audio/mpeg'
    assert audio['url'].endswith(f'/audio/{job.id}.mp3')
    media_route=f'/podcasts/{token}/audio/{job.id}.mp3'
    media=client.get(media_route,headers={'Range':'bytes=0-3'})
    assert media.status_code==206 and len(media.content)==4
    assert media.headers['content-type']=='audio/mpeg'
    assert client.head(media_route).headers['content-length']==str(derivative.audio_bytes)
    assert client.head(media_route).content==b''
    assert client.get(f'/podcasts/{token}/audio/{job.id}',headers={'Range':'bytes=0-3'}).content==media.content
    assert media.headers['cache-control']=='private, no-store'
    rotated=client.post(endpoint,headers=auth_headers).json()['feed_url']
    assert client.get(route).status_code==404 and client.get(media_route).status_code==404
    assert ET.fromstring(client.get(rotated).content).findtext('channel/item/guid')==guid
    assert client.delete(endpoint,headers=auth_headers).status_code==204
    assert client.get(rotated).status_code==404


def test_podcast_owner_scope_disabled_and_missing_recordings(client,auth_headers,db,test_user,test_library,tmp_path,monkeypatch):
    from app.models import User, Library
    novel,job,path=fixture(db,test_user,test_library,tmp_path,monkeypatch)
    other=User(username='other-podcast',password='hash');db.add(other);db.flush()
    library=Library(name='other',user_id=other.id);db.add(library);db.flush()
    other_story=Novel(title='Other',library_id=library.id);db.add(other_story);db.commit()
    assert client.post(f'/audio/stories/{other_story.id}/podcast',headers=auth_headers).status_code==404
    url=client.post(f'/audio/stories/{novel.id}/podcast',headers=auth_headers).json()['feed_url']
    token=url.split('/podcasts/')[1].split('/')[0]
    assert client.get(f'/podcasts/{token}/audio/9999').status_code==404
    path.unlink()
    assert ET.fromstring(client.get(url).content).find('channel/item') is None
    path.symlink_to(tmp_path/'elsewhere.wav');(tmp_path/'elsewhere.wav').write_bytes(b'private')
    assert client.get(f'/podcasts/{token}/audio/{job.id}').status_code==404
    test_user.is_disabled=True;db.commit()
    assert client.get(url).status_code==404
    assert client.get(f'/podcasts/{token}/audio/{job.id}').status_code==404


def test_podcast_token_redaction():
    from app.logging_config import redact_url
    assert redact_url('/api/podcasts/secret/feed.xml')=='/api/podcasts/***/feed.xml'
    assert redact_url('/podcasts/secret/audio/12')=='/podcasts/***/audio/12'


def test_account_removal_purges_private_feed_and_audiobooks(client,auth_headers,db,test_user,test_library,tmp_path,monkeypatch):
    from app.models.audio_export import AudioExportJob
    from app.services.account_service import delete_user_account
    novel,job,path=fixture(db,test_user,test_library,tmp_path,monkeypatch)
    monkeypatch.setenv('DOWNLOAD_PATH',str(tmp_path))
    url=client.post(f'/audio/stories/{novel.id}/podcast',headers=auth_headers).json()['feed_url']
    folder=tmp_path/'audio-exports'/str(test_user.id)/'1';folder.mkdir(parents=True)
    output=folder/'book.m4b';output.write_bytes(b'private export')
    export=AudioExportJob(user_id=test_user.id,novel_id=novel.id,fingerprint='a'*64,title='Private',
        chapters=[],total_chapters=1,status='completed',audio_path=str(output),audio_bytes=14)
    db.add(export);db.commit()
    delete_user_account(db,test_user)
    assert db.query(PodcastFeedToken).count()==0
    assert db.query(AudioExportJob).count()==0
    assert not output.exists() and not path.exists()
    assert client.get(url).status_code==404


def test_canonical_https_base_overrides_internal_proxy_scheme(client,auth_headers,db,test_user,test_library,tmp_path,monkeypatch):
    novel,job,path=fixture(db,test_user,test_library,tmp_path,monkeypatch)
    monkeypatch.setattr(settings,'NEXUS_PUBLIC_API_URL','https://reading.example/nexus/api')
    result=client.post(f'/audio/stories/{novel.id}/podcast',headers={**auth_headers,
        'x-forwarded-prefix':'/api','x-forwarded-host':'internal:8180','x-forwarded-proto':'http'})
    assert result.status_code==201
    url=result.json()['feed_url'];assert url.startswith('https://reading.example/nexus/api/podcasts/')
    prepare(db)
    route='/podcasts/'+url.split('/podcasts/')[1]
    enclosure=ET.fromstring(client.get(route,headers={'x-forwarded-proto':'http'}).content).find('channel/item/enclosure')
    assert enclosure.attrib['url'].startswith('https://reading.example/nexus/api/podcasts/')


def test_podcasts_require_valid_private_credential(client):
    for token in ("invalid", "x"*43):
        for suffix in ("feed.xml", "audio/1"):
            response=client.get(f"/podcasts/{token}/{suffix}")
            assert response.status_code==404
            assert response.headers['cache-control']=='private, no-store'
