"""Build private M4Bs from completed recordings; never generate speech.

FFmpeg metadata and chapter mapping follow https://ffmpeg.org/ffmpeg-formats.html
and https://ffmpeg.org/ffmpeg.html#Advanced-options. Markers derive from PCM
frame counts, with microsecond metadata and the container's own precision.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from fractions import Fraction
import shutil
import stat
import subprocess
import tempfile
import time
import wave
from datetime import timedelta

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from app.models.audio_export import AudioExportJob
from app.models.audio_job import ChapterAudioJob
from app.models.chapter import Chapter
from app.models.library import Library
from app.models.novel import Novel
from app.models.user import User
from app.services.job_lease import claim, heartbeat, recover_expired, utcnow
from config.settings import settings

ACTIVE = ('queued', 'processing', 'retry_wait')
MAX_SECONDS = 7 * 24 * 3600
MAX_SOURCE_BYTES = 128 * 1024**3
MAX_OUTPUT_BYTES = 8 * 1024**3
EXPORT_TIMEOUT = 7200
PREFLIGHT_TIMEOUT = 12


class ExportError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


class ExportStopped(Exception):
    pass


def download_root():
    return Path(os.path.abspath(os.getenv('DOWNLOAD_PATH', settings.DOWNLOAD_PATH)))


def safe_path(path, base, *, required=True):
    path, base = Path(os.path.abspath(path)), Path(os.path.abspath(base))
    try:
        path.relative_to(base)
        anchor = download_root()
        parts = path.relative_to(anchor).parts
    except ValueError:
        raise ExportError('unsafe_source', 'This recording is outside private Nexus storage. Generate or restore it again.') from None
    current = anchor
    for part in ('', *parts):
        current = current / part
        if current.is_symlink():
            raise ExportError('unsafe_source', 'Symbolic links cannot be used for private audio exports.')
    if required and not path.is_file():
        raise ExportError('source_missing', 'A selected recording was removed. Restore it or create a new export with available chapters.')
    return path


def source_path(path, user_id):
    return safe_path(path, download_root() / 'audio' / str(user_id))


def export_directory(user_id, job_id=None):
    base = download_root() / 'audio-exports'
    path = base / str(user_id)
    if job_id is not None:
        path /= str(job_id)
    safe_path(path, download_root(), required=False)
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


def _signature(path, *, deadline=None):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        return _descriptor_signature(fd, deadline=deadline)
    finally:
        os.close(fd)


def _descriptor_signature(fd, *, deadline=None, should_stop=lambda: False):
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise ExportError('unsafe_source', 'Only regular audio files can be exported.')
    if before.st_size > MAX_SOURCE_BYTES:
        raise ExportError('too_large', 'Choose fewer chapters for this export (128 GiB source limit)')
    digest = hashlib.sha256()
    consumed = 0
    os.lseek(fd, 0, os.SEEK_SET)
    while True:
        if should_stop():
            raise ExportError('worker_stopped', 'Export interrupted by worker shutdown. Completed recordings are preserved; retry the export.')
        if deadline is not None and time.monotonic() >= deadline:
            raise ExportError('source_hash_timeout', 'Reading the selected recordings took too long. Choose fewer chapters and try again.')
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        consumed += len(chunk)
        if consumed > before.st_size:
            raise ExportError('source_changed', 'A selected recording changed. Create a new export from the current recordings.')
        digest.update(chunk)
    after = os.fstat(fd)
    os.lseek(fd, 0, os.SEEK_SET)
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ExportError('source_changed', 'A selected recording changed. Create a new export from the current recordings.')
    # Content hashes survive restore; inode/device/subsecond mtimes do not.
    return {'size': after.st_size, 'sha256': digest.hexdigest()}


def queue_export(db, *, user_id, novel_id, audio_job_ids):
    deadline = time.monotonic() + PREFLIGHT_TIMEOUT
    db.query(User.id).filter_by(id=user_id).with_for_update().first()
    novel = db.query(Novel).join(Library, Library.id == Novel.library_id).filter(
        Novel.id == novel_id, Library.user_id == user_id).first()
    if not novel:
        raise ExportError('not_found', 'Story not found')
    recordings = db.query(ChapterAudioJob, Chapter).join(Chapter, Chapter.id == ChapterAudioJob.chapter_id).filter(
        ChapterAudioJob.id.in_(audio_job_ids), ChapterAudioJob.user_id == user_id,
        ChapterAudioJob.novel_id == novel.id, Chapter.novel_id == novel.id).order_by(Chapter.chapter_number, Chapter.id).with_for_update(of=[ChapterAudioJob, Chapter]).execution_options(include_archived_chapters=True).all()
    if len(recordings) != len(audio_job_ids):
        raise ExportError('not_found', 'One or more chapter recordings were not found')
    if len({chapter.id for _, chapter in recordings}) != len(recordings):
        raise ExportError('duplicate_chapter', 'Choose one recording for each chapter')
    snapshot, source_bytes = [], 0
    for audio, chapter in recordings:
        if audio.status != 'completed' or not audio.audio_path:
            raise ExportError('not_ready', 'Wait until every selected chapter recording is complete')
        path = source_path(audio.audio_path, user_id)
        source_bytes += path.stat().st_size
        if source_bytes > MAX_SOURCE_BYTES:
            raise ExportError('too_large', 'Choose fewer chapters for this export (128 GiB source limit)')
        from app.services.audio_identity_service import fields
        provenance = fields(db, audio, chapter)
        if not provenance['source_identity_current']:
            raise ExportError('source_changed', 'This recording belongs to an earlier chapter identity. Its original file remains available; select a recording with preserved chapter metadata for a new book export.')
        snapshot.append({'chapter_key': audio.chapter_key, 'manifest_epoch': audio.manifest_epoch,
            'manifest_revision': audio.manifest_revision, 'chapter_archived': chapter.archived, 'audio_job_id': audio.id, 'chapter_number': chapter.chapter_number,
            'title': audio.chapter_title_snapshot if audio.chapter_title_snapshot is not None else chapter.title or f'Chapter {chapter.chapter_number}',
            'original_chapter_number': audio.chapter_number_snapshot, 'source_version': audio.source_version,
            'path': str(path), 'file': _signature(path, deadline=deadline)})
    if sum(item['file']['size'] for item in snapshot) > MAX_SOURCE_BYTES:
        raise ExportError('too_large', 'Choose fewer chapters for this export (128 GiB source limit)')
    fingerprint = hashlib.sha256(json.dumps({'pipeline': 1, 'title': novel.title, 'chapters': snapshot}, sort_keys=True).encode()).hexdigest()
    existing = db.query(AudioExportJob).filter_by(user_id=user_id, novel_id=novel.id, fingerprint=fingerprint).first()
    if existing:
        return existing
    job = AudioExportJob(user_id=user_id, novel_id=novel.id, fingerprint=fingerprint,
        title=novel.title, chapters=snapshot, total_chapters=len(snapshot))
    try:
        with db.begin_nested():
            db.add(job); db.flush()
    except IntegrityError:
        return db.query(AudioExportJob).filter_by(user_id=user_id, novel_id=novel.id, fingerprint=fingerprint).one()
    db.commit(); db.refresh(job)
    return job


def ready_path(job):
    if job.status != 'completed' or not job.audio_path:
        return None
    try:
        return safe_path(job.audio_path, download_root() / 'audio-exports' / str(job.user_id) / str(job.id))
    except ExportError:
        return None


def metadata_escape(value):
    value = ''.join(character for character in str(value).replace('\r', '') if ord(character) >= 32 or character in '\n\t')
    return ''.join('\\' + character if character in '=;#\\\n' else character for character in value)


def _pcm_duration(fd):
    try:
        with os.fdopen(os.dup(fd), 'rb') as handle, wave.open(handle, 'rb') as audio:
            count, rate = audio.getnframes(), audio.getframerate()
            channels, width = audio.getnchannels(), audio.getsampwidth()
            if audio.getcomptype() != 'NONE' or not 8000 <= rate <= 96000 or channels not in (1, 2) or width not in (1, 2, 3, 4) or not 0 < count <= rate * MAX_SECONDS:
                raise ValueError()
            audio.setpos(count - 1)
            if len(audio.readframes(1)) != channels * width:
                raise ValueError()
        os.lseek(fd, 0, os.SEEK_SET)
        return Fraction(count, rate)
    except (OSError, ValueError, wave.Error, EOFError):
        raise ExportError('invalid_audio', 'A selected WAV recording is incomplete or unsupported. Restore or regenerate it first.') from None


def _open_sources(snapshot, user_id, *, deadline=None, should_stop=lambda: False):
    descriptors, measured, elapsed = [], [], Fraction(0)
    try:
        for item in snapshot:
            path = source_path(item['path'], user_id)
            before = path.stat()
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
            descriptors.append(fd)
            value = os.fstat(fd)
            if (_descriptor_signature(fd, deadline=deadline, should_stop=should_stop) != item['file'] or (before.st_dev, before.st_ino) != (value.st_dev, value.st_ino)
                    or not stat.S_ISREG(value.st_mode)):
                raise ExportError('source_changed', 'A selected recording changed. Create a new export from the current recordings.')
            duration = _pcm_duration(fd)
            measured.append({**item, 'duration_seconds': float(duration), 'start_seconds': float(elapsed), 'end_seconds': float(elapsed + duration),
                'start_us': round(elapsed * 1_000_000), 'end_us': round((elapsed + duration) * 1_000_000)})
            elapsed += duration
            if elapsed > MAX_SECONDS:
                raise ExportError('too_large', 'Choose fewer chapters for this export (seven days of audio per file)')
        return descriptors, measured, elapsed
    except Exception:
        for fd in descriptors:
            os.close(fd)
        raise


def _current(db, job_id, owner):
    db.expire_all()
    job = db.get(AudioExportJob, job_id)
    if (job is None or job.status != 'processing' or job.lease_owner != owner
            or job.lease_expires_at is None or job.lease_expires_at <= utcnow()):
        raise ExportStopped()
    return job


def _stop_process(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=5)


def _encode(descriptors, measured, title, output, directory, db, job_id, owner, should_stop, *, deadline=None):
    executable = shutil.which('ffmpeg')
    if not executable or not shutil.which('ffprobe'):
        raise ExportError('encoder_unavailable', 'Install ffmpeg and ffprobe on the Nexus worker to create M4B files.')
    metadata = directory / 'chapters.ffmetadata'
    contents = [';FFMETADATA1', 'title=' + metadata_escape(title), 'media_type=2']
    for item in measured:
        contents.extend(('[CHAPTER]', 'TIMEBASE=1/1000000', f"START={item['start_us']}", f"END={item['end_us']}", 'title=' + metadata_escape(item['title'])))
    metadata.write_text('\n'.join(contents) + '\n', encoding='utf8'); metadata.chmod(0o600)
    progress = directory / 'progress.txt'
    command = [executable, '-nostdin', '-hide_banner', '-v', 'error', '-xerror', '-y', '-filter_complex_threads', '1']
    for fd in descriptors:
        command.extend(('-threads', '1', '-protocol_whitelist', 'file', '-f', 'wav', '-i', f'/dev/fd/{fd}'))
    command.extend(('-protocol_whitelist', 'file', '-f', 'ffmetadata', '-i', str(metadata)))
    filters = [f'[{index}:a:0]aresample=24000,aformat=sample_fmts=fltp:channel_layouts=mono[a{index}]' for index in range(len(descriptors))]
    filters.append(''.join(f'[a{index}]' for index in range(len(descriptors))) + f'concat=n={len(descriptors)}:v=0:a=1[book]')
    command.extend(('-filter_complex', ';'.join(filters), '-map', '[book]', '-map_metadata', str(len(descriptors)),
        '-map_chapters', str(len(descriptors)), '-vn', '-c:a', 'aac', '-b:a', '96k', '-threads', '1',
        '-movflags', '+faststart', '-progress', str(progress), '-f', 'ipod', str(output)))
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, pass_fds=tuple(descriptors))
    deadline = deadline if deadline is not None else time.monotonic() + EXPORT_TIMEOUT
    try:
        while process.poll() is None:
            if should_stop():
                raise ExportError('worker_stopped', 'Export interrupted by worker shutdown. Completed recordings are preserved; retry the export.')
            job = _current(db, job_id, owner)
            if time.monotonic() >= deadline:
                raise ExportError('encoder_timeout', 'The export exceeded its processing limit. Retry with fewer chapters.')
            if output.exists() and output.stat().st_size > MAX_OUTPUT_BYTES:
                raise ExportError('too_large', 'Choose fewer chapters for this export (8 GiB file limit)')
            if progress.exists():
                with progress.open('rb') as handle:
                    handle.seek(max(0, progress.stat().st_size - 8192))
                    lines = handle.read(8192).decode('utf8', errors='ignore').splitlines()
                values = [line.split('=', 1)[1] for line in lines if line.startswith('out_time_us=')]
                if values and values[-1].lstrip('-').isdigit():
                    completed = sum(item['end_us'] <= int(values[-1]) for item in measured)
                    if completed > job.completed_chapters:
                        db.execute(update(AudioExportJob).where(AudioExportJob.id == job_id, AudioExportJob.status == 'processing',
                            AudioExportJob.lease_owner == owner).values(completed_chapters=completed))
                        db.commit()
            time.sleep(.25)
        if process.returncode != 0:
            raise ExportError('encoder_failed', 'The M4B encoder could not finish. Check available storage and selected WAV recordings, then retry.')
    finally:
        _stop_process(process)


def _verify_output(path, measured, total):
    result = subprocess.run([shutil.which('ffprobe'), '-v', 'error', '-show_chapters', '-show_streams', '-show_format', '-of', 'json', str(path)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=20, check=True)
    if len(result.stdout) > 2_000_000:
        raise ExportError('encoder_failed', 'The encoded file could not be validated.')
    data = json.loads(result.stdout)
    if (not any(stream.get('codec_name') == 'aac' and stream.get('codec_type') == 'audio' for stream in data.get('streams', []))
        or len(data.get('chapters', [])) != len(measured)
        or abs(float(data['format']['duration']) - float(total)) > .25):
        raise ExportError('encoder_failed', 'The encoded file did not preserve its chapter markers. Retry the export.')
    for actual, expected in zip(data['chapters'], measured):
        if (abs(float(actual['start_time']) - expected['start_seconds']) > .002
                or abs(float(actual['end_time']) - expected['end_seconds']) > .002
                or actual.get('tags', {}).get('title') != ''.join(c for c in expected['title'].replace('\r', '') if ord(c) >= 32 or c in '\n\t')):
            raise ExportError('encoder_failed', 'The encoded file did not preserve its chapter markers. Retry the export.')


def process_export_job(job_id, session_factory, *, should_stop=lambda: False):
    descriptors, promoted = [], None
    with session_factory() as db:
        job = claim(db, AudioExportJob, job_id)
        if job is None:
            return
        owner, user_id = job.lease_owner, job.user_id
        attempt_count, max_attempts = job.attempt_count, job.max_attempts
        reset = db.execute(update(AudioExportJob).where(AudioExportJob.id == job_id,
            AudioExportJob.status == 'processing', AudioExportJob.lease_owner == owner).values(completed_chapters=0))
        db.commit()
        if reset.rowcount != 1:
            return
        deadline = time.monotonic() + EXPORT_TIMEOUT
        try:
            with heartbeat(session_factory, AudioExportJob, job.id, owner):
                descriptors, measured, total = _open_sources(job.chapters, user_id, deadline=deadline, should_stop=should_stop)
                directory = export_directory(user_id, job.id)
                with tempfile.TemporaryDirectory(prefix='attempt-', dir=directory) as temporary:
                    temp = Path(temporary); output = temp / 'book.m4b'
                    _encode(descriptors, measured, job.title, output, temp, db, job.id, owner, should_stop, deadline=deadline)
                    _current(db, job.id, owner)
                    if any(_descriptor_signature(fd, deadline=deadline, should_stop=should_stop) != item['file'] for fd, item in zip(descriptors, measured)):
                        raise ExportError('source_changed', 'A selected recording changed. Create a new export from the current recordings.')
                    _verify_output(output, measured, total)
                    if not 0 < output.stat().st_size <= MAX_OUTPUT_BYTES:
                        raise ExportError('too_large', 'Choose fewer chapters for this export (8 GiB file limit)')
                    _current(db, job.id, owner)
                    promoted = directory / f'book-{owner}.m4b'
                    output.chmod(0o600); os.replace(output, promoted)
                    saved = db.execute(update(AudioExportJob).where(AudioExportJob.id == job.id,
                        AudioExportJob.status == 'processing', AudioExportJob.lease_owner == owner).values(
                            status='completed', chapters=measured, total_chapters=len(measured), completed_chapters=len(measured),
                            audio_path=str(promoted), audio_bytes=promoted.stat().st_size, duration_seconds=float(total),
                            finished_at=utcnow(), error=None, error_code=None, lease_owner=None, lease_expires_at=None))
                    if saved.rowcount != 1:
                        db.rollback(); raise ExportStopped()
                    db.commit(); promoted = None
        except ExportStopped:
            db.rollback()
        except Exception as exc:
            db.rollback()
            code = exc.code if isinstance(exc, ExportError) else 'encoder_failed'
            message = str(exc) if isinstance(exc, ExportError) else 'The M4B export could not finish. Check available storage and retry.'
            permanent = code in {'unsafe_source', 'source_missing', 'source_changed', 'invalid_audio', 'too_large', 'encoder_unavailable'}
            db.execute(update(AudioExportJob).where(AudioExportJob.id == job_id, AudioExportJob.status == 'processing',
                AudioExportJob.lease_owner == owner).values(status='failed' if permanent or attempt_count >= max_attempts else 'retry_wait',
                    error_code=code, error=message, lease_owner=None, lease_expires_at=None,
                    finished_at=utcnow() if permanent or attempt_count >= max_attempts else None,
                    next_attempt_at=utcnow() + timedelta(seconds=30 * 2**min(attempt_count-1, 6))))
            db.commit()
        finally:
            for fd in descriptors:
                os.close(fd)
            if promoted is not None:
                promoted.unlink(missing_ok=True)


def process_due_exports(session_factory, *, should_stop=lambda: False):
    with session_factory() as db:
        recover_expired(db, AudioExportJob)
        job = db.query(AudioExportJob.id).filter(AudioExportJob.status.in_(('queued', 'retry_wait')),
            or_(AudioExportJob.next_attempt_at.is_(None), AudioExportJob.next_attempt_at <= utcnow())).order_by(AudioExportJob.created_at, AudioExportJob.id).first()
    if job and not should_stop():
        process_export_job(job.id, session_factory, should_stop=should_stop)


def cancel_user_exports(db, user_id):
    """Call inside account removal's transaction, before removing private files."""
    return db.query(AudioExportJob).filter(AudioExportJob.user_id == user_id, AudioExportJob.status.in_(ACTIVE)).update(
        {'status':'cancelled', 'lease_owner':None, 'lease_expires_at':None}, synchronize_session=False)


def purge_export_files(user_id):
    root = download_root() / 'audio-exports' / str(user_id)
    safe_path(root, download_root(), required=False)
    if root.exists():
        shutil.rmtree(root)


def audio_export_storage_bytes(user_id):
    root = download_root() / 'audio-exports' / str(user_id)
    safe_path(root, download_root(), required=False)
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [name for name in dirs if not (Path(directory) / name).is_symlink()]
        for name in files:
            path = Path(directory) / name
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
    return total


def delete_export(db, job):
    if job.status in ACTIVE:
        raise ExportError('active_export', 'Cancel the export before deleting it')
    directory = download_root() / 'audio-exports' / str(job.user_id) / str(job.id)
    safe_path(directory, download_root(), required=False)
    if directory.exists():
        shutil.rmtree(directory)
    db.delete(job); db.commit()
