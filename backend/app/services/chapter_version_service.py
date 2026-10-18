"""Snapshot originals in the same transaction as source replacement."""
import json
from datetime import UTC, datetime
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from app.models.chapter_version import ChapterVersion
from app.services.chapter_document import from_text


def document_for(chapter):
    return chapter.document or from_text(chapter.content or "")


def retain_current(db, chapter, reason="source_update"):
    document = document_for(chapter)
    if not document.get("blocks"):
        return
    # Conflict-safe across retries and repeated A -> B -> A source revisions.
    insert = postgres_insert if db.bind.dialect.name == "postgresql" else sqlite_insert
    now = datetime.now(UTC)
    values = dict(chapter_id=chapter.id, chapter_key=chapter.chapter_key, content_version=document["content_version"],
        title=chapter.title, source_url=chapter.source_url, content=document["plain_text"],
        document=document, byte_count=len(json.dumps(document, ensure_ascii=False).encode("utf-8")),
        reason=reason, created_at=now, updated_at=now)
    db.execute(insert(ChapterVersion).values(**values).on_conflict_do_nothing(
        index_elements=["chapter_key", "content_version"]))


def version_summary(version, *, current=False):
    return {"content_version": version.content_version, "title": version.title,
        "saved_at": version.created_at, "byte_count": version.byte_count,
        "current": current, "reason": version.reason}
