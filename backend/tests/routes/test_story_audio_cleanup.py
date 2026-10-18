from pathlib import Path
from uuid import uuid4
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine,event
from sqlalchemy.orm import sessionmaker
from app.models import User,Library,Novel,Chapter,ChapterAudioJob,ChapterAudioPart,ReadingRun,ReadingRunEvent
from app.models.audio_export import AudioExportJob
from app.models.podcast_audio import PodcastAudioJob
from app.models.podcast import PodcastFeedToken
from app.models.download_job import ChapterDownloadJob
from config.database import Base
from config.settings import settings
from app.services import novel_services,library_services,story_audio_cleanup


def story(db,root,user,library,title):
    book=Novel(title=title,library_id=library.id);db.add(book);db.flush()
    run=ReadingRun(user_id=user.id,novel_id=book.id,run_key=str(uuid4()),ordinal=1,progress_snapshot={})
    db.add(run);db.flush()
    db.add(ReadingRunEvent(user_id=user.id,novel_id=book.id,run_key=run.run_key,kind='started',inferred=True))
    chapter=Chapter(novel_id=book.id,chapter_number=1,title='One');db.add(chapter);db.flush()
    source=ChapterAudioJob(user_id=user.id,library_id=library.id,novel_id=book.id,chapter_id=chapter.id,
        status='processing',lease_owner='audio-worker',provider_id='fixture',provider_url='unused',provider_model='fixture',provider_voice='fixture')
    db.add(source);db.flush()
    recording=root/'audio'/str(user.id)/str(book.id)/str(chapter.id)/str(source.id)/'part.wav'
    recording.parent.mkdir(parents=True);recording.write_bytes(b'private original audio')
    source.audio_path=str(recording)
    db.add(ChapterAudioPart(job_id=source.id,part_index=0,text='private words',status='completed',audio_path=str(recording)))
    export=AudioExportJob(user_id=user.id,novel_id=book.id,fingerprint=str(book.id).zfill(64),title=title,
        chapters=[],total_chapters=1,status='processing',lease_owner='export-worker')
    derivative=PodcastAudioJob(user_id=user.id,novel_id=book.id,source_audio_job_id=source.id,chapter_number=1,
        pipeline_version='fixture',source_snapshot={},status='processing',lease_owner='podcast-worker')
    db.add_all([export,derivative]);db.flush()
    audiobook=root/'audio-exports'/str(user.id)/str(export.id)/'attempt'/'partial.m4b'
    podcast=root/'podcast-audio'/str(user.id)/str(derivative.id)/'attempt'/'partial.mp3'
    legacy=root/user.username/str(library.id)/title/'book.epub'
    for path in (audiobook,podcast,legacy):path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'private artifact')
    export.audio_path=str(audiobook);derivative.audio_path=str(podcast)
    db.add(PodcastFeedToken(user_id=user.id,novel_id=book.id,token_hash=str(book.id).zfill(64)))
    db.add(ChapterDownloadJob(user_id=user.id,library_id=library.id,novel_id=book.id,chapter_id=chapter.id,status='processing',lease_owner='download-worker'))
    db.commit()
    return SimpleNamespace(book_id=book.id,source_id=source.id,export_id=export.id,podcast_id=derivative.id,
        paths=[recording,audiobook,podcast,legacy])


@pytest.mark.parametrize('foreign_keys',[False,True])
@pytest.mark.parametrize('remove_library',[False,True])
def test_story_and_library_cleanup_commit_fences_workers_and_preserves_siblings(tmp_path,monkeypatch,foreign_keys,remove_library):
    root=tmp_path/'private-storage';root.mkdir()
    monkeypatch.setattr(settings,'DOWNLOAD_PATH',str(root));monkeypatch.setenv('DOWNLOAD_PATH',str(root))
    engine=create_engine(f'sqlite:///{tmp_path / "lifecycle.db"}')
    @event.listens_for(engine,'connect')
    def configure(connection,_):connection.execute(f'PRAGMA foreign_keys={int(foreign_keys)}')
    Base.metadata.create_all(engine)
    try:
        with sessionmaker(bind=engine)() as db:
            owner=User(username='owner',password='unused');other=User(username='other',password='unused')
            db.add_all([owner,other]);db.flush()
            library=Library(user_id=owner.id,name='Target');kept=Library(user_id=owner.id,name='Keep');foreign=Library(user_id=other.id,name='Other')
            db.add_all([library,kept,foreign]);db.commit()
            target=story(db,root,owner,library,'Target book');same_library=story(db,root,owner,library,'Sibling book')
            other_library=story(db,root,owner,kept,'Other library book');other_account=story(db,root,other,foreign,'Other account book')
            library_id=library.id
            removed=[target,same_library] if remove_library else [target]
            preserved=[other_library,other_account] if remove_library else [same_library,other_library,other_account]
            original=story_audio_cleanup.finish_story_audio_removal
            observed=[]
            def finish(plan):
                assert db.get(Novel,plan.novel_id) is None
                assert db.query(AudioExportJob).filter_by(novel_id=plan.novel_id).count()==0
                assert db.query(PodcastAudioJob).filter_by(novel_id=plan.novel_id).count()==0
                assert db.query(ReadingRun).filter_by(novel_id=plan.novel_id).count()==0
                assert db.query(ReadingRunEvent).filter_by(novel_id=plan.novel_id).count()==0
                observed.append(plan.novel_id)
                original(plan)
            monkeypatch.setattr(story_audio_cleanup,'finish_story_audio_removal',finish)
            if remove_library:library_services.delete_library(db,library_id)
            else:novel_services.delete_novel(db,target.book_id)
            assert sorted(observed)==sorted(item.book_id for item in removed)
            for item in removed:
                assert not any(path.exists() for path in item.paths)
                assert db.get(ChapterAudioJob,item.source_id) is None
                assert db.query(ChapterAudioPart).filter_by(job_id=item.source_id).count()==0
                assert db.query(ChapterDownloadJob).filter_by(novel_id=item.book_id).count()==0
                assert db.query(PodcastFeedToken).filter_by(novel_id=item.book_id).count()==0
            for item in preserved:
                assert all(path.is_file() for path in item.paths)
                assert db.get(Novel,item.book_id) is not None
                assert db.query(ReadingRun).filter_by(novel_id=item.book_id).count()==1
                assert db.query(ReadingRunEvent).filter_by(novel_id=item.book_id).count()==1
                assert db.get(ChapterAudioJob,item.source_id).status=='processing'
                assert db.get(AudioExportJob,item.export_id).lease_owner=='export-worker'
                assert db.get(PodcastAudioJob,item.podcast_id).lease_owner=='podcast-worker'
    finally:engine.dispose()


def test_failed_story_delete_keeps_database_and_private_files(tmp_path,monkeypatch):
    root=tmp_path/'storage';root.mkdir();monkeypatch.setattr(settings,'DOWNLOAD_PATH',str(root))
    engine=create_engine(f'sqlite:///{tmp_path / "rollback.db"}');Base.metadata.create_all(engine)
    try:
        with sessionmaker(bind=engine)() as db:
            user=User(username='owner',password='unused');db.add(user);db.flush()
            library=Library(user_id=user.id,name='Library');db.add(library);db.commit()
            target=story(db,root,user,library,'Keep until committed')
            def fail_commit():raise RuntimeError('Simulated transaction failure')
            monkeypatch.setattr(db,'commit',fail_commit)
            with pytest.raises(RuntimeError,match='transaction failure'):novel_services.delete_novel(db,target.book_id)
            assert db.get(Novel,target.book_id) is not None
            assert db.get(AudioExportJob,target.export_id).status=='processing'
            assert db.get(PodcastAudioJob,target.podcast_id).status=='processing'
            assert all(path.is_file() for path in target.paths)
    finally:engine.dispose()
