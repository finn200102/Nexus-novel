"""Durable background worker for automatic chapter downloads and digests."""

import asyncio
import signal
from datetime import UTC, datetime
from sqlalchemy import or_

from config.database import SessionLocal
from app.models.download_job import ChapterDownloadJob
from app.models.follow import UserNovelFollow
from app.models.update_event import NovelUpdateEvent
from app.routers.chapter import run_queued_download


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


def process_downloads(db) -> int:
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
    for job_id in ids:
        run_queued_download(job_id, SessionLocal)
    return len(ids)


async def run() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    while not stop.is_set():
        db = SessionLocal()
        try:
            process_downloads(db)
            release_due_notifications(db)
        finally:
            db.close()
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except asyncio.TimeoutError:
            pass


if __name__ == "__main__":
    asyncio.run(run())
