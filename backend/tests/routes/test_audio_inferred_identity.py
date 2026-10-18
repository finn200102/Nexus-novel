"""Migration-inferred bindings do not become narration authority."""
from sqlalchemy.orm import sessionmaker
from app.models import ChapterAudioJob
from app.models.podcast_audio import PodcastAudioJob
from app.services import audio_job_service as audio,podcast_audio_service
from tests.routes.test_audio_chapter_identity import seed,single,captured,transport


def test_inferred_completed_recording_remains_private_without_current_attachment(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    novel,chapter=seed(db,test_user,test_library,monkeypatch,tmp_path)
    job_id=single(client,auth_headers,chapter,captured(chapter)).json()['id']
    transport(monkeypatch,[]);audio.process_audio_job(job_id,sessionmaker(bind=db.get_bind()))
    job=db.get(ChapterAudioJob,job_id);job.identity_inferred=True;db.commit()
    saved=client.get(f'/audio/jobs/{job_id}',headers=auth_headers)
    assert saved.status_code==200,saved.text
    assert saved.json()['audio_ready'] and saved.json()['source_identity_inferred']
    assert not saved.json()['source_identity_current'] and saved.json()['chapter_number'] is None
    assert saved.json()['chapter_key'] is None
    assert client.get(f'/audio/jobs/{job_id}/audio',headers=auth_headers).status_code==200
    manifest=client.get(f'/audio/jobs/{job_id}/manifest',headers=auth_headers).json()
    assert not manifest['current_source']
    page=client.get(f'/audio/stories/{novel.id}',headers=auth_headers).json()
    current=next(row for row in page['chapters'] if row['chapter_number']==chapter.chapter_number)
    assert current['latest_job'] is None
    retained=client.get(f'/audio/stories/{novel.id}/recordings?limit=1',headers=auth_headers)
    assert retained.status_code==200,retained.text
    assert retained.json()['total']==1 and retained.json()['items'][0]['id']==job_id
    assert retained.json()['items'][0]['source_identity_inferred'] is True
    assert client.get(f'/audio/stories/{novel.id}/recordings?offset=1',headers=auth_headers).json()['items']==[]
    assert client.get(f'/audio/stories/{novel.id}/recordings?limit=101',headers=auth_headers).status_code==422
    feed=client.post(f'/audio/stories/{novel.id}/podcast',headers=auth_headers)
    assert feed.status_code==201,feed.text
    assert podcast_audio_service.discover(db,user_id=test_user.id,novel_id=novel.id)==0
    assert db.query(PodcastAudioJob).count()==0


def test_inferred_queued_job_requires_review_before_any_new_speech(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    _,chapter=seed(db,test_user,test_library,monkeypatch,tmp_path)
    job_id=single(client,auth_headers,chapter,captured(chapter)).json()['id']
    job=db.get(ChapterAudioJob,job_id);job.identity_inferred=True;db.commit()
    calls=[];transport(monkeypatch,calls)
    audio.process_audio_job(job_id,sessionmaker(bind=db.get_bind()))
    db.expire_all();job=db.get(ChapterAudioJob,job_id)
    assert not calls and job.status=='failed' and job.error_code=='audio_identity_review_required'
    retry=client.post(f'/audio/jobs/{job_id}/retry',headers=auth_headers)
    assert retry.status_code==409


def test_saved_recording_list_does_not_expose_another_household_account(client,auth_headers,db,test_user,test_library,monkeypatch,tmp_path):
    from app.models import User,Library,Novel
    other=User(username='different-narrator-owner',password='unused');db.add(other);db.flush()
    library=Library(user_id=other.id,name='Other private library');db.add(library);db.flush()
    novel=Novel(library_id=library.id,title='PRIVATE_OTHER_STORY');db.add(novel);db.commit()
    response=client.get(f'/audio/stories/{novel.id}/recordings',headers=auth_headers)
    assert response.status_code==404 and 'PRIVATE_OTHER_STORY' not in response.text
