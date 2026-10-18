"""Small CPU-only MP3 derivatives for explicitly activated private feeds.

Original narration is never queued or generated here. RSS reads only finished
files; a leased worker converts existing recordings while the feed is active.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
from datetime import timedelta

from sqlalchemy import and_, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import load_only
from app.models.audio_job import ChapterAudioJob
from app.models.chapter import Chapter
from app.models.chapter_manifest import ChapterManifestState
from app.models.library import Library
from app.models.novel import Novel
from app.models.podcast import PodcastFeedToken
from app.models.podcast_audio import PodcastAudioJob
from app.models.user import User
from app.services import podcast_service
from app.services.audio_export_service import _descriptor_signature, _pcm_duration, ExportError
from app.services.job_lease import claim, heartbeat, recover_expired, utcnow
from config.settings import settings

PIPELINE = 'mp3-mono-44100-96k-v1'
ACTIVE = ('queued', 'processing', 'retry_wait')
TIMEOUT = 1800
MAX_SECONDS = 24 * 3600
MAX_BYTES = 2 * 1024**3


class Stopped(Exception):
    pass


def _root():
    return Path(settings.DOWNLOAD_PATH).absolute()


def private_path(path, user_id, job_id=None, *, required=True):
    storage, path = _root(), Path(path).absolute()
    try:
        try:
            relative = path.relative_to(storage)
        except ValueError:
            relative = path.relative_to(storage.resolve())
        prefix = ('podcast-audio',str(user_id)) + ((str(job_id),) if job_id is not None else ())
        if relative.parts[:len(prefix)] != prefix:
            raise ValueError()
        current = storage
        for part in ('',*relative.parts):
            if part in ('.','..'):
                raise ValueError()
            current /= part
            if current.is_symlink():
                raise ValueError()
        if required and not current.is_file():
            raise ValueError()
        return current
    except (ValueError,OSError):
        raise ExportError('unsafe_audio','This podcast audio file is missing or outside private Nexus storage.') from None


def ready_file(job):
    if job is None or job.status!='completed' or not job.audio_path:
        return None
    try:
        return private_path(job.audio_path,job.user_id,job.id)
    except ExportError:
        return None


def _ranked_sources(db,user_id=None,novel_id=None):
    ranked=db.query(ChapterAudioJob.id.label('id'),func.row_number().over(
        partition_by=(ChapterAudioJob.user_id,ChapterAudioJob.chapter_id),
        order_by=(ChapterAudioJob.finished_at.desc().nullslast(),ChapterAudioJob.updated_at.desc().nullslast(),ChapterAudioJob.id.desc())).label('rank')).filter(
        ChapterAudioJob.status=='completed',ChapterAudioJob.audio_path.isnot(None),ChapterAudioJob.identity_inferred.is_(False))
    if user_id is not None:ranked=ranked.filter(ChapterAudioJob.user_id==user_id)
    if novel_id is not None:ranked=ranked.filter(ChapterAudioJob.novel_id==novel_id)
    return ranked.subquery()


def latest_sources(db,user_id=None,novel_id=None):
    ranked=_ranked_sources(db,user_id,novel_id)
    return db.query(ChapterAudioJob,Chapter,PodcastAudioJob).join(ranked,ranked.c.id==ChapterAudioJob.id).join(
        Chapter,Chapter.id==ChapterAudioJob.chapter_id).join(ChapterManifestState,
        ChapterManifestState.novel_id==Chapter.novel_id).outerjoin(PodcastAudioJob,and_(
            PodcastAudioJob.source_audio_job_id==ChapterAudioJob.id,
            PodcastAudioJob.user_id==ChapterAudioJob.user_id,PodcastAudioJob.pipeline_version==PIPELINE)).filter(
        ranked.c.rank==1,Chapter.novel_id==ChapterAudioJob.novel_id,
        ChapterAudioJob.chapter_key==Chapter.chapter_key,
        ChapterAudioJob.manifest_epoch==ChapterManifestState.manifest_epoch).options(load_only(Chapter.id,Chapter.chapter_number,Chapter.title))


def _eligible(db):
    return latest_sources(db).join(PodcastFeedToken,and_(PodcastFeedToken.user_id==ChapterAudioJob.user_id,
        PodcastFeedToken.novel_id==ChapterAudioJob.novel_id)).join(User,User.id==ChapterAudioJob.user_id).join(
        Novel,Novel.id==ChapterAudioJob.novel_id).join(Library,Library.id==Novel.library_id).filter(
        User.is_disabled.is_(False),Library.user_id==ChapterAudioJob.user_id)


def discover(db,*,user_id=None,novel_id=None,limit=20):
    query=_eligible(db).filter(PodcastAudioJob.id.is_(None))
    if user_id is not None:query=query.filter(ChapterAudioJob.user_id==user_id)
    if novel_id is not None:query=query.filter(ChapterAudioJob.novel_id==novel_id)
    created=0
    for source,chapter,_ in query.order_by(ChapterAudioJob.id).limit(min(limit,100)).all():
        db.query(User.id).filter_by(id=source.user_id).with_for_update().first()
        current=_eligible(db).filter(ChapterAudioJob.id==source.id,PodcastAudioJob.id.is_(None)).populate_existing().first()
        if current is None:
            continue
        source,chapter,_=current
        snapshot={'chapter_title_snapshot':source.chapter_title_snapshot,'chapter_number_snapshot':source.chapter_number_snapshot,
            'chapter_key':source.chapter_key,'manifest_epoch':source.manifest_epoch,'manifest_revision':source.manifest_revision,
            'path':source.audio_path,'source_version':source.source_version,'title':source.chapter_title_snapshot if source.chapter_title_snapshot is not None else chapter.title or f'Chapter {chapter.chapter_number}'}
        job=PodcastAudioJob(user_id=source.user_id,novel_id=source.novel_id,source_audio_job_id=source.id,
            chapter_number=chapter.chapter_number,pipeline_version=PIPELINE,source_snapshot=snapshot)
        try:
            with db.begin_nested():db.add(job);db.flush()
            created+=1
        except IntegrityError:
            pass
    db.commit()
    return created


def activate(db,user_id,novel_id):
    if podcast_service.token_row(db,user_id,novel_id) is None:return
    db.query(User.id).filter_by(id=user_id).with_for_update().first()
    wanted=latest_sources(db,user_id,novel_id).with_entities(ChapterAudioJob.id)
    db.query(PodcastAudioJob).filter_by(user_id=user_id,novel_id=novel_id,status='cancelled').filter(
        PodcastAudioJob.source_audio_job_id.in_(wanted)).update({
        'status':'queued','lease_owner':None,'lease_expires_at':None,'attempt_count':0,'next_attempt_at':None,
        'finished_at':None,'error':None,'error_code':None},synchronize_session=False)
    db.commit()
    discover(db,user_id=user_id,novel_id=novel_id)


def status(db,user_id,novel_id,*,offset=0,limit=50):
    enabled=podcast_service.token_row(db,user_id,novel_id) is not None
    result={'active':enabled,'feed_url':None,'format':'mp3','ready':0,'pending':0,'failed':0,'episodes':[],
        'episodes_total':0,'episodes_offset':offset,'episodes_limit':limit}
    if not enabled:return result
    for source,chapter,job in latest_sources(db,user_id,novel_id).order_by(Chapter.chapter_number).yield_per(100):
        path=ready_file(job)
        state='completed' if path else job.status if job else 'queued'
        error_code,error=(job.error_code,job.error) if job else (None,None)
        if job is not None and job.status=='completed' and path is None:
            state,error_code,error='failed','file_missing','Podcast audio was removed. Retry to prepare it from the original recording.'
        bucket='ready' if state=='completed' else 'failed' if state in ('failed','cancelled') else 'pending'
        result[bucket]+=1
        index=result['episodes_total'];result['episodes_total']+=1
        if offset<=index<offset+limit:
            result['episodes'].append({'id':job.id if job else None,'source_audio_job_id':source.id,
                'chapter_number':chapter.chapter_number,'chapter_key':chapter.chapter_key,
                'manifest_epoch':chapter.novel.manifest_state.manifest_epoch,
                'manifest_revision':str(chapter.novel.manifest_state.revision),
                'source_version':source.source_version,'status':state,'audio_bytes':job.audio_bytes if job else None,
                'duration_seconds':job.duration_seconds if job else None,'error_code':error_code,'error':error})
    return result


def _current(db,job_id,owner):
    db.expire_all();job=db.get(PodcastAudioJob,job_id)
    if (job is None or job.status!='processing' or job.lease_owner!=owner
            or job.lease_expires_at is None or job.lease_expires_at<=utcnow()):raise Stopped()
    active=db.query(PodcastFeedToken.id).join(User,User.id==PodcastFeedToken.user_id).join(Novel,Novel.id==PodcastFeedToken.novel_id).join(
        Library,Library.id==Novel.library_id).filter(PodcastFeedToken.user_id==job.user_id,PodcastFeedToken.novel_id==job.novel_id,
        User.is_disabled.is_(False),Library.user_id==job.user_id).first()
    if active is None:raise Stopped()
    if latest_sources(db,job.user_id,job.novel_id).filter(ChapterAudioJob.id==job.source_audio_job_id).first() is None:raise Stopped()
    return job


def _stop(process):
    if process.poll() is None:
        process.terminate()
        try:process.wait(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)


def _encode(fd,output,db,job_id,owner,deadline,should_stop):
    encoder=shutil.which('ffmpeg')
    if not encoder or not shutil.which('ffprobe'):
        raise ExportError('encoder_unavailable','Install ffmpeg and ffprobe on the Nexus worker to prepare podcast MP3 audio.')
    process=subprocess.Popen([encoder,'-nostdin','-v','error','-xerror','-y','-threads','1','-filter_threads','1',
        '-protocol_whitelist','file','-f','wav','-i',f'/dev/fd/{fd}','-map','0:a:0','-vn','-sn','-dn',
        '-map_metadata','-1','-ar','44100','-ac','1','-c:a','libmp3lame','-b:a','96k','-threads','1',
        '-id3v2_version','3','-write_xing','1','-f','mp3',str(output)],
        stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,pass_fds=(fd,))
    try:
        while process.poll() is None:
            _current(db,job_id,owner)
            if should_stop():raise ExportError('worker_stopped','Podcast preparation was interrupted. The original recording is preserved; retry preparation.')
            if time.monotonic()>=deadline:raise ExportError('encoder_timeout','Podcast preparation exceeded its time limit. Check the recording and retry.')
            if output.exists() and output.stat().st_size>MAX_BYTES:raise ExportError('too_large','This chapter exceeds the podcast audio file limit.')
            time.sleep(.25)
        if process.returncode!=0:raise ExportError('encoder_failed','Podcast MP3 preparation failed. Check worker storage and ffmpeg support, then retry.')
    finally:_stop(process)


def _verify(path,duration):
    result=subprocess.run([shutil.which('ffprobe'),'-v','error','-show_streams','-show_format','-of','json',str(path)],
        stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,stdin=subprocess.DEVNULL,timeout=15,check=True)
    if len(result.stdout)>100_000:raise ValueError()
    data=json.loads(result.stdout)
    if (not any(s.get('codec_name')=='mp3' and s.get('codec_type')=='audio' and int(s.get('sample_rate',0))==44100
                and s.get('channels')==1 for s in data.get('streams',[]))
            or abs(float(data['format']['duration'])-duration)>.25):raise ValueError()


def process_job(job_id,session_factory,*,should_stop=lambda:False):
    fd,promoted=None,None
    with session_factory() as db:
        job=claim(db,PodcastAudioJob,job_id)
        if job is None:return
        owner,attempt,max_attempt=job.lease_owner,job.attempt_count,job.max_attempts
        user_id=job.user_id;deadline=time.monotonic()+TIMEOUT
        try:
            with heartbeat(session_factory,PodcastAudioJob,job_id,owner):
                job=_current(db,job_id,owner)
                source=db.query(ChapterAudioJob).filter_by(id=job.source_audio_job_id,user_id=user_id,novel_id=job.novel_id,status='completed').first()
                if source is None:raise ExportError('source_missing','The original recording was removed. Prepare chapter audio again before enabling this episode.')
                snapshot=job.source_snapshot
                if (source.source_version!=snapshot.get('source_version') or source.audio_path!=snapshot['path']
                        or source.chapter_key!=snapshot.get('chapter_key') or source.manifest_epoch!=snapshot.get('manifest_epoch')):
                    raise ExportError('source_changed','The original recording changed. Use its current narration to prepare a new episode.')
                path=podcast_service.audio_path(source)
                if path is None:raise ExportError('source_missing','The original recording is missing or unsafe. Restore it or prepare chapter audio again.')
                before=path.stat();fd=os.open(path,os.O_RDONLY|getattr(os,'O_NOFOLLOW',0));actual=os.fstat(fd)
                if (before.st_dev,before.st_ino)!=(actual.st_dev,actual.st_ino) or not stat.S_ISREG(actual.st_mode):raise ExportError('source_changed','The original recording changed. Prepare a new episode.')
                signature=_descriptor_signature(fd,deadline=deadline,should_stop=should_stop)
                if snapshot.get('file') and snapshot['file']!=signature:raise ExportError('source_changed','The original recording changed. Prepare a new episode.')
                duration=float(_pcm_duration(fd))
                if duration>MAX_SECONDS:raise ExportError('too_large','This recording exceeds the 24-hour podcast episode limit.')
                snapshot={**snapshot,'file':signature}
                saved=db.execute(update(PodcastAudioJob).where(PodcastAudioJob.id==job_id,PodcastAudioJob.status=='processing',PodcastAudioJob.lease_owner==owner).values(source_snapshot=snapshot))
                if saved.rowcount!=1:db.rollback();raise Stopped()
                db.commit()
                directory=private_path(_root()/'podcast-audio'/str(user_id)/str(job_id),user_id,job_id,required=False)
                directory.mkdir(parents=True,exist_ok=True,mode=0o700);directory.chmod(0o700)
                with tempfile.TemporaryDirectory(prefix='attempt-',dir=directory) as temporary:
                    output=Path(temporary)/'episode.mp3'
                    _encode(fd,output,db,job_id,owner,deadline,should_stop)
                    _current(db,job_id,owner)
                    if _descriptor_signature(fd,deadline=deadline,should_stop=should_stop)!=signature:raise ExportError('source_changed','The original recording changed during conversion. Prepare a new episode.')
                    _verify(output,duration)
                    if not 0<output.stat().st_size<=MAX_BYTES:raise ExportError('too_large','This chapter exceeds the podcast audio file limit.')
                    _current(db,job_id,owner)
                    promoted=directory/f'episode-{owner}.mp3';output.chmod(0o600);os.replace(output,promoted)
                    saved=db.execute(update(PodcastAudioJob).where(PodcastAudioJob.id==job_id,PodcastAudioJob.status=='processing',PodcastAudioJob.lease_owner==owner).values(
                        status='completed',audio_path=str(promoted),audio_bytes=promoted.stat().st_size,duration_seconds=duration,
                        finished_at=utcnow(),error=None,error_code=None,lease_owner=None,lease_expires_at=None))
                    if saved.rowcount!=1:db.rollback();raise Stopped()
                    db.commit();promoted=None
        except Stopped:
            db.rollback()
            db.execute(update(PodcastAudioJob).where(PodcastAudioJob.id==job_id,PodcastAudioJob.status=='processing',PodcastAudioJob.lease_owner==owner).values(
                status='cancelled',lease_owner=None,lease_expires_at=None,finished_at=utcnow()))
            db.commit()
        except Exception as exc:
            db.rollback()
            code=exc.code if isinstance(exc,ExportError) else 'encoder_failed'
            message=str(exc) if isinstance(exc,ExportError) else 'Podcast MP3 preparation could not finish. Check the worker and retry.'
            permanent=code in ('source_missing','source_changed','invalid_audio','unsafe_audio','too_large','encoder_unavailable')
            db.execute(update(PodcastAudioJob).where(PodcastAudioJob.id==job_id,PodcastAudioJob.status=='processing',PodcastAudioJob.lease_owner==owner).values(
                status='failed' if permanent or attempt>=max_attempt else 'retry_wait',error_code=code,error=message,
                finished_at=utcnow() if permanent or attempt>=max_attempt else None,next_attempt_at=utcnow()+timedelta(seconds=30*2**min(attempt-1,6)),
                lease_owner=None,lease_expires_at=None))
            db.commit()
        finally:
            if fd is not None:os.close(fd)
            if promoted is not None:promoted.unlink(missing_ok=True)


def process_due_podcast_audio(session_factory,*,should_stop=lambda:False):
    with session_factory() as db:
        recover_expired(db,PodcastAudioJob);discover(db)
        active=db.query(PodcastFeedToken.user_id.label('user_id'),PodcastFeedToken.novel_id.label('novel_id')).subquery()
        ranked=_ranked_sources(db)
        job=db.query(PodcastAudioJob.id).join(active,and_(active.c.user_id==PodcastAudioJob.user_id,active.c.novel_id==PodcastAudioJob.novel_id)).filter(
            PodcastAudioJob.status.in_(('queued','retry_wait')),or_(PodcastAudioJob.next_attempt_at.is_(None),PodcastAudioJob.next_attempt_at<=utcnow())).join(
            ranked,and_(ranked.c.id==PodcastAudioJob.source_audio_job_id,ranked.c.rank==1)).order_by(PodcastAudioJob.created_at,PodcastAudioJob.id).first()
    if job and not should_stop():process_job(job.id,session_factory,should_stop=should_stop)


def cancel_podcast_audio(db,user_id,novel_id=None):
    query=db.query(PodcastAudioJob).filter(PodcastAudioJob.user_id==user_id,PodcastAudioJob.status.in_(ACTIVE))
    if novel_id is not None:query=query.filter(PodcastAudioJob.novel_id==novel_id)
    return query.update({'status':'cancelled','lease_owner':None,'lease_expires_at':None,'finished_at':utcnow()},synchronize_session=False)


def purge_podcast_audio_files(user_id):
    directory=private_path(_root()/'podcast-audio'/str(user_id),user_id,required=False)
    if directory.exists():shutil.rmtree(directory)


def podcast_audio_storage_bytes(user_id):
    directory=private_path(_root()/'podcast-audio'/str(user_id),user_id,required=False)
    total=0
    for parent,dirs,files in os.walk(directory,followlinks=False):
        dirs[:]=[name for name in dirs if not (Path(parent)/name).is_symlink()]
        for name in files:
            path=Path(parent)/name
            if path.is_file() and not path.is_symlink():total+=path.stat().st_size
    return total


def delete_podcast_audio_for_source(db,source):
    jobs=db.query(PodcastAudioJob).filter_by(user_id=source.user_id,source_audio_job_id=source.id).all()
    for job in jobs:
        directory=private_path(_root()/'podcast-audio'/str(source.user_id)/str(job.id),source.user_id,job.id,required=False)
        if directory.exists():shutil.rmtree(directory)
        db.delete(job)
    db.flush()
