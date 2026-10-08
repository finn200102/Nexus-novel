"""Durable background worker for automatic chapter downloads and digests."""

import asyncio
import logging
import signal
from datetime import UTC, datetime
from sqlalchemy import or_

from config.database import SessionLocal, engine
from config.settings import settings
from app.db_migrations import upgrade_database
from app.models.download_job import ChapterDownloadJob
from app.models.audio_job import ChapterAudioJob
from app.models.follow import UserNovelFollow
from app.models.update_event import NovelUpdateEvent
from app.routers.chapter import run_queued_download
from app.services.audio_job_service import process_audio_job
from app.services.notification_delivery import deliver_due_notifications


def release_due_notifications(db) -> int:
    changed = 0
    now = datetime.now(UTC)
    events = (
        db.query(NovelUpdateEvent)
        .filter(NovelUpdateEvent.notification_visible.is_(False))
        .order_by(NovelUpdateEvent.created_at.asc())
        .limit(500)
        .all()
    )
    for event in events:
        follow = (
            db.query(UserNovelFollow)
            .filter(
                UserNovelFollow.user_id == event.user_id,
                UserNovelFollow.novel_id == event.novel_id,
            )
            .first()
        )
        if not follow:
            continue
        should_release = False
        if follow.notification_policy == "after_n":
            hidden = (
                db.query(NovelUpdateEvent)
                .filter(
                    NovelUpdateEvent.user_id == event.user_id,
                    NovelUpdateEvent.novel_id == event.novel_id,
                    NovelUpdateEvent.notification_visible.is_(False),
                )
                .all()
            )
            should_release = sum(item.chapter_count for item in hidden) >= max(follow.notification_count or 1, 1)
        elif follow.notification_policy == "daily_digest" and event.created_at:
            should_release = event.created_at.date() < now.date()
        elif follow.notification_policy == "weekly_digest" and event.created_at:
            should_release = event.created_at.date().isocalendar()[:2] < now.date().isocalendar()[:2]
        if should_release:
            event.notification_visible = True
            changed += 1
    if changed:
        db.commit()
    return changed


def process_downloads() -> int:
    db = SessionLocal()
    jobs = (
        db.query(ChapterDownloadJob)
        .filter(
            or_(
                ChapterDownloadJob.status == "queued",
                (ChapterDownloadJob.status == "retry_wait")
                & (ChapterDownloadJob.next_attempt_at <= datetime.now(UTC)),
            )
        )
        .order_by(ChapterDownloadJob.created_at.asc())
        .limit(10)
        .all()
    )
    ids = [job.id for job in jobs]
    db.expunge_all()
    db.close()
    for job_id in ids:
        run_queued_download(job_id, SessionLocal)
    return len(ids)


def process_notifications() -> int:
    """Send released update events to push devices and Apprise channels.

    Runs on a worker thread so slow push services never stall the loop, and
    logs rather than raises so one bad delivery cannot stop the worker.
    """
    db = SessionLocal()
    try:
        return deliver_due_notifications(db).events
    except Exception:
        logging.getLogger(__name__).exception("Notification delivery failed")
        db.rollback()
        return 0
    finally:
        db.close()


def process_audio_jobs() -> int:
    db = SessionLocal()
    try:
        now = datetime.now(UTC).replace(tzinfo=None)
        jobs = (
            db.query(ChapterAudioJob)
            .filter(
                or_(
                    ChapterAudioJob.status == "queued",
                    (ChapterAudioJob.status == "retry_wait") & (ChapterAudioJob.next_attempt_at <= now),
                )
            )
            .order_by(ChapterAudioJob.created_at.asc())
            .limit(2)
            .all()
        )
        ids = [job.id for job in jobs]
    finally:
        db.close()
    for job_id in ids:
        process_audio_job(job_id, SessionLocal)
    return len(ids)


async def run() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    while not stop.is_set():
        # The downloader is synchronous internally and bridges to async source
        # clients with asyncio.run(). Keep it off this worker's event loop.
        await asyncio.to_thread(process_downloads)
        await asyncio.to_thread(process_audio_jobs)
        db = SessionLocal()
        try:
            release_due_notifications(db)
        finally:
            db.close()
        await asyncio.to_thread(process_notifications)
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass


if __name__ == "__main__":
    if settings.RUN_MIGRATIONS_ON_STARTUP:
        # Normally a no-op: the API migrates first and both hold the same
        # advisory lock, so a simultaneous start waits instead of racing.
        upgrade_database(engine)
    asyncio.run(run())
