"""Fence story-owned audio jobs transactionally; remove files only after commit."""
from app.models.reader_guide import PrivateGuideJob, PrivateGuideArtifact
from dataclasses import dataclass
import logging
from pathlib import Path
import shutil

from app.models.audio_job import ChapterAudioJob,ChapterAudioPart
from app.models.audio_export import AudioExportJob
from app.models.podcast import PodcastFeedToken
from app.models.podcast_audio import PodcastAudioJob
from app.models.download_job import ChapterDownloadJob
from app.models.reading_run import ReadingRun,ReadingRunEvent
from app.models.reading_continuity import ReadingContinuity
from app.models.source_migration import SourceMigration
from app.models.reading_progress import ReadingProgress,ReadingProgressOperation
from app.models.reading_history import ReadingHistory
from config.settings import settings


@dataclass
class RemovalPlan:
    user_id:int
    novel_id:int
    directories:list[Path]
    files:list[Path]


def _safe(path,root):
    """Allow aliases above the volume; reject links or traversal inside it."""
    root,path=Path(root).absolute(),Path(path).absolute()
    try:
        try:relative=path.relative_to(root)
        except ValueError:relative=path.relative_to(root.resolve())
        current=root
        for part in ('',*relative.parts):
            if part in ('.','..'):raise ValueError()
            current/=part
            if current.is_symlink():raise ValueError()
        return current
    except (ValueError,OSError):return None


def stage_story_audio_removal(db,novel):
    """Called before deleting a novel, in the same DB transaction."""
    user=novel.library.user
    user_id,novel_id=user.id,novel.id
    root=Path(settings.DOWNLOAD_PATH).absolute()
    directories=[root/'audio'/str(user_id)/str(novel_id)]
    files=[]
    exports=db.query(AudioExportJob).filter_by(user_id=user_id,novel_id=novel_id)
    podcasts=db.query(PodcastAudioJob).filter_by(user_id=user_id,novel_id=novel_id)
    directories += [root/'audio-exports'/str(user_id)/str(row.id) for row in exports.all()]
    directories += [root/'podcast-audio'/str(user_id)/str(row.id) for row in podcasts.all()]
    jobs=db.query(ChapterAudioJob).filter_by(user_id=user_id,novel_id=novel_id)
    ids=[row.id for row in jobs.all()]
    paths=[row.audio_path for row in jobs.all() if row.audio_path]
    if ids:
        paths += [row.audio_path for row in db.query(ChapterAudioPart).filter(ChapterAudioPart.job_id.in_(ids)).all() if row.audio_path]
    # Some legacy narration jobs have per-owner files outside the numeric
    # story directory. Remove only paths explicitly attached to this story.
    owner_audio=root/'audio'/str(user_id)
    for path in paths:
        candidate=_safe(path,root)
        if candidate is not None:
            try:candidate.relative_to(owner_audio);files.append(candidate)
            except ValueError:
                try:candidate.resolve().relative_to(owner_audio.resolve());files.append(candidate)
                except ValueError:pass
    # Legacy EPUB/title folders retain their strict direct-child boundary.
    if all(value and Path(value).name==value and value not in ('.','..') for value in (user.username,novel.title or '')):
        directories.append(root/user.username/str(novel.library_id)/novel.title)
    for query,model in ((exports,AudioExportJob),(podcasts,PodcastAudioJob),(jobs,ChapterAudioJob)):
        query.filter(model.status.in_(('queued','processing','retry_wait'))).update(
            {'status':'cancelled','lease_owner':None,'lease_expires_at':None},synchronize_session=False)
    # Keep the canonical fact for surviving continuations, without a dangling
    # attribution pointer on SQLite configurations that disable FK actions.
    db.query(ReadingContinuity).filter_by(user_id=user_id,completion_novel_id=novel_id).update(
        {'completion_novel_id':None},synchronize_session=False)
    # Keep account-owned audit/operation receipts after either story is deleted,
    # including installations with SQLite FK enforcement disabled.
    for column in (SourceMigration.source_novel_id, SourceMigration.target_novel_id):
        db.query(SourceMigration).filter(SourceMigration.user_id==user_id,column==novel_id).update(
            {column:None},synchronize_session=False)
    # Account accounting receipts remain; private story artifacts/jobs do not.
    db.query(PrivateGuideArtifact).filter_by(user_id=user_id, novel_id=novel_id).delete(synchronize_session=False)
    db.query(PrivateGuideJob).filter_by(user_id=user_id, novel_id=novel_id).delete(synchronize_session=False)
    # Explicit child deletion also supports SQLite without FK enforcement.
    for model in (ReadingHistory,ReadingProgressOperation,ReadingProgress):
        db.query(model).filter_by(user_id=user_id,novel_id=novel_id).delete(synchronize_session=False)
    db.query(ReadingRunEvent).filter_by(user_id=user_id,novel_id=novel_id).delete(synchronize_session=False)
    db.query(ReadingRun).filter_by(user_id=user_id,novel_id=novel_id).delete(synchronize_session=False)
    podcasts.delete(synchronize_session=False)
    exports.delete(synchronize_session=False)
    db.query(PodcastFeedToken).filter_by(user_id=user_id,novel_id=novel_id).delete(synchronize_session=False)
    if ids:
        db.query(ChapterAudioPart).filter(ChapterAudioPart.job_id.in_(ids)).delete(synchronize_session=False)
    jobs.delete(synchronize_session=False)
    downloads=db.query(ChapterDownloadJob).filter_by(user_id=user_id,novel_id=novel_id)
    downloads.filter(ChapterDownloadJob.status.in_(('queued','processing','retry_wait'))).update(
        {'status':'cancelled','lease_owner':None,'lease_expires_at':None},synchronize_session=False)
    downloads.delete(synchronize_session=False)
    return RemovalPlan(user_id,novel_id,directories,files)


def finish_story_audio_removal(plan):
    """Call only after commit; another story/account's directories are never touched."""
    root=Path(settings.DOWNLOAD_PATH).absolute()
    failed=False
    for item in plan.files:
        path=_safe(item,root)
        if path is None:failed=True;continue
        try:path.unlink(missing_ok=True)
        except OSError:failed=True
    for item in plan.directories:
        path=_safe(item,root)
        if path is None:failed=True;continue
        try:
            if path.is_dir():shutil.rmtree(path)
        except OSError:failed=True
    if failed:
        logging.getLogger(__name__).warning('Private audio cleanup needs administrator attention for story %s',plan.novel_id)
