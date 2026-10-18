"""Saving a user's reading position, shared by the reader and the activity inbox."""

from datetime import date, datetime
import hashlib
import json
from types import SimpleNamespace
from fastapi import HTTPException

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.chapter import Chapter
from app.models.reading_history import ReadingHistory
from app.models.reading_progress import ReadingProgress, ReadingProgressOperation
from app.models.user import User
from app.services.reading_stats_service import record_progress_crossing
from app.services.chapter_document import from_text
from app.models.chapter_read_receipt import ChapterReadReceipt
from app.services.reading_run_service import current_run, ensure_run, check_run_key, update_run, progress_view, restore_progress


_SERVER_POSITION_ONLY = object()


def save_server_selected_position(db: Session, *, user_id, chapter, expected_chapter_key, expected_manifest_epoch,
        expected_manifest_revision, position, percent, expected_revision=None, reading_run_key=None):
    """An explicit server-selected skip changes position, never read-version proof.

    Captured identity is mandatory even on the internal path; callers cannot
    silently bind a stale selected chapter to the latest topology.
    """
    return save_reading_progress(db,user_id=user_id,chapter=chapter,position=position,percent=percent,
        expected_revision=expected_revision,reading_run_key=reading_run_key,expected_chapter_key=expected_chapter_key,
        expected_manifest_epoch=expected_manifest_epoch,expected_manifest_revision=expected_manifest_revision,
        _position_only_authority=_SERVER_POSITION_ONLY)


def save_reading_progress(db: Session, *, user_id: int, chapter: Chapter, position: int, percent: float,
                         expected_revision=None, operation_id=None, device_id=None,
                         block_id=None, text_offset=0, intent="automatic", content_version=None,
                         text_quote=None, quote_prefix=None, quote_suffix=None, locator_variant=None, reading_run_key=None, expected_chapter_key=None, expected_manifest_epoch=None,
                         expected_manifest_revision=None, expected_content_version=None, submitted_chapter_number=None, _position_only_authority=None) -> ReadingProgress:
    """Store the user's position in ``chapter`` and add a compact daily history point. Commits."""
    position_only=_position_only_authority is _SERVER_POSITION_ONLY
    from app.services.chapter_identity_service import sqlite_transaction
    sqlite_transaction(db,write=True)
    # Lock the account even when no progress row exists yet. This serializes
    # first inserts and operation receipts on PostgreSQL.
    user=db.query(User).filter(User.id == user_id).populate_existing().with_for_update().first()
    if user is None or user.is_disabled:raise HTTPException(401,'Account is unavailable')
    from app.auth.dependencies import require_current_session
    require_current_session(db,user_id)
    operation = [chapter.id, position, percent, block_id, text_offset, intent]
    if position_only:operation.append({'server_position_only':True})
    if content_version is not None:
        operation.append(content_version)
    if any(value is not None for value in (text_quote, quote_prefix, quote_suffix, locator_variant)):
        operation.append({"text_quote": text_quote, "quote_prefix": quote_prefix, "quote_suffix": quote_suffix, "locator_variant": locator_variant})
    if reading_run_key is not None:
        operation.append({"reading_run_key": str(reading_run_key)})
    expected_identity=dict(expected_chapter_key=expected_chapter_key,expected_manifest_epoch=expected_manifest_epoch,
        expected_manifest_revision=expected_manifest_revision,expected_content_version=expected_content_version)
    if any(value is not None for value in expected_identity.values()):
        operation.append(expected_identity)
        if submitted_chapter_number is not None:operation.append({"chapter_number":submitted_chapter_number})
    signature = hashlib.sha256(json.dumps(operation).encode()).hexdigest()
    if operation_id:
        receipt = db.query(ReadingProgressOperation).filter_by(user_id=user_id, operation_id=operation_id).first()
        if receipt:
            if receipt.fingerprint != signature or receipt.novel_id != chapter.novel_id:
                raise HTTPException(409, detail={"code": "operation_reused", "message": "This save identifier was already used for a different change"})
            return SimpleNamespace(**receipt.response)
    from app.services.chapter_identity_service import check_write
    captured=check_write(db,user_id,chapter,**expected_identity,require_content_version=not position_only)
    if submitted_chapter_number is not None and submitted_chapter_number!=chapter.chapter_number:
        raise HTTPException(409,detail={"code":"chapter_manifest_changed","message":"The supplied chapter address no longer belongs to this identity.","current":captured})
    progress = db.query(ReadingProgress).filter(
        ReadingProgress.user_id == user_id,
        ReadingProgress.novel_id == chapter.novel_id,
    ).first()
    run = current_run(db, user_id, chapter.novel_id, progress)
    recovering = progress is None
    if recovering:progress = restore_progress(run)
    check_run_key(run, reading_run_key, progress)
    if expected_revision is not None and expected_revision != (progress.revision if progress else 0):
        current = progress_view(progress)
        raise HTTPException(409, detail={"code": "progress_conflict", "current": current,
                                        "message": "Another device changed your reading position. Both positions have been kept."})
    actual_version = (chapter.document or from_text(chapter.content or ""))["content_version"]
    if content_version is not None and content_version != actual_version and intent not in {"rewind", "reconcile"}:
        raise HTTPException(409, detail={"code": "content_changed", "current": {"chapter_number": progress.chapter_number if progress else chapter.chapter_number,
            "percent": (progress.percent or 0) if progress else 0, "revision": (progress.revision or 0) if progress else 0,
            "position": (progress.position or 0) if progress else 0,
            "content_version": actual_version, "reading_run_key": progress.reading_run_key if progress else None}, "message": "This chapter changed while you were offline. Review the new text before marking it read."})
    if not progress:
        progress = ReadingProgress(user_id=user_id, novel_id=chapter.novel_id)
        db.add(progress)
    if recovering:db.add(progress)
    run = ensure_run(db, user_id, chapter.novel_id, progress, legacy=progress.chapter_number is not None)
    previous_chapter, previous_percent = progress.chapter_number, progress.percent or 0
    previous_locator_version = progress.locator_content_version
    progress.chapter_id = chapter.id
    progress.chapter_key=chapter.chapter_key
    progress.current_identity_inferred=False
    progress.manifest_epoch=captured['manifest_epoch']
    progress.manifest_revision=captured['manifest_revision']
    read_version=None if position_only else content_version or expected_content_version
    verified_version=read_version if read_version==actual_version else None
    progress.source_content_version=verified_version
    progress.chapter_number = chapter.chapter_number
    progress.position = max(position, 0)
    progress.percent = min(max(percent, 0), 100)
    progress.revision = (progress.revision or 0) + 1
    progress.block_id = block_id
    progress.text_offset = text_offset
    progress.text_quote, progress.quote_prefix, progress.quote_suffix = text_quote, quote_prefix, quote_suffix
    progress.locator_content_version, progress.locator_variant = content_version, locator_variant
    progress.device_id = device_id
    furthest = (progress.furthest_chapter_number or 0, progress.furthest_percent or 0)
    # A fresh reading uses (0, 0) as its unread sentinel. The first actual
    # position may precede zero; an already visited zero must never be lost.
    first_negative = chapter.chapter_number < 0 and furthest == (0, 0) and previous_percent == 0 and (
        previous_chapter is None or (run.requires_run_key and not (run.progress_snapshot or {}).get('_portable_source_key')
            and not db.query(ReadingHistory.id).filter_by(user_id=user_id, novel_id=chapter.novel_id,
                reading_run_key=run.run_key).first()))
    if first_negative or (chapter.chapter_number, progress.percent) > furthest:
        progress.furthest_chapter_number = chapter.chapter_number
        progress.furthest_percent = progress.percent
        progress.furthest_chapter_key=chapter.chapter_key
        progress.furthest_identity_inferred=0
        progress.furthest_content_version=verified_version
    elif progress.furthest_chapter_key==chapter.chapter_key and progress.percent>=progress.furthest_percent:
        progress.furthest_identity_inferred=0
        if verified_version is not None:progress.furthest_content_version=verified_version
    record_progress_crossing(
        db, user_id=user_id, novel_id=chapter.novel_id, chapter_number=chapter.chapter_number,
        previous_chapter=previous_chapter, previous_percent=previous_percent, percent=progress.percent,
    )
    # Persist a compact history point once per chapter/day. It powers streaks
    # and velocity without recording raw scrolling or text selection data.
    today = date.today()
    history = db.query(ReadingHistory).filter(
        ReadingHistory.user_id == user_id,
        ReadingHistory.novel_id == chapter.novel_id,
        ((ReadingHistory.chapter_key==chapter.chapter_key) | ((ReadingHistory.chapter_key.is_(None)) & (ReadingHistory.chapter_number==chapter.chapter_number))),
        ReadingHistory.reading_run_key == run.run_key,
        func.date(ReadingHistory.reading_date) == today.isoformat(),
    ).first()
    if history:
        previous_completion = (history.max_percent or 0) >= 100
        previous_max=history.max_percent or 0
        history.max_percent = max(previous_max, int(progress.percent))
        history.chapter_key=chapter.chapter_key
        if history.identity_inferred and progress.percent>=previous_max:
            history.identity_inferred=False
        if verified_version is not None:
            history.verified_percent=max(history.verified_percent or 0,int(progress.percent)) if history.verified_content_version==verified_version else int(progress.percent)
            history.verified_content_version=verified_version
    else:
        previous_completion = previous_chapter == chapter.chapter_number and previous_percent >= 100
        db.add(ReadingHistory(
            user_id=user_id,
            novel_id=chapter.novel_id,
            chapter_number=chapter.chapter_number,
            chapter_key=chapter.chapter_key,
            identity_inferred=False,
            verified_content_version=verified_version,
            verified_percent=int(progress.percent) if verified_version is not None else 0,
            reading_date=datetime.combine(today, datetime.min.time()),
            max_percent=int(progress.percent),
            reading_run_key=run.run_key,
        ))
    db.flush()
    if verified_version == actual_version:
        read_receipt = db.query(ChapterReadReceipt).filter_by(user_id=user_id, chapter_key=chapter.chapter_key, content_version=actual_version).first()
        if read_receipt is None:
            older_version = db.query(ChapterReadReceipt).filter(ChapterReadReceipt.user_id == user_id,
                ChapterReadReceipt.chapter_key == chapter.chapter_key, ChapterReadReceipt.content_version != actual_version).first()
            read_receipt = ChapterReadReceipt(user_id=user_id, chapter_id=chapter.id, chapter_key=chapter.chapter_key, content_version=actual_version,
                completed=False, requires_review=bool(older_version or previous_completion
                    or (previous_chapter == chapter.chapter_number and previous_percent > 0 and previous_locator_version != actual_version)))
            db.add(read_receipt)
        if percent >= 100 and (not read_receipt.requires_review or intent == "confirm_read"):
            read_receipt.completed, read_receipt.requires_review = True, False
    db.flush()
    update_run(db, run, progress)
    if operation_id:
        response = {key: getattr(progress, key) for key in (
            "chapter_key", "furthest_chapter_key", "current_identity_inferred", "furthest_identity_inferred", "manifest_epoch", "manifest_revision", "source_content_version", "furthest_content_version",
            "novel_id", "chapter_number", "position", "percent", "revision", "furthest_chapter_number",
            "furthest_percent", "block_id", "text_offset", "text_quote", "quote_prefix", "quote_suffix", "locator_content_version", "locator_variant", "reading_run_key",
        )}
        response["updated_at"] = progress.updated_at.isoformat()
        db.add(ReadingProgressOperation(user_id=user_id, novel_id=chapter.novel_id, operation_id=operation_id,
                                        fingerprint=signature, response=response))
    db.commit()
    db.refresh(progress)
    return progress
