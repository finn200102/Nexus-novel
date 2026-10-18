"""Export a user's highlights and private notes as Markdown, zip or Readwise highlights."""

import io
import json
import re
import zipfile
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
from sqlalchemy.orm import Session
from sqlalchemy import func,and_, DateTime
from fastapi import HTTPException
from app.auth.dependencies import require_current_session

from app.models.chapter import Chapter
from app.models.novel import Novel
from app.models.novel_personal import NovelPersonalData
from app.models.reading_annotation import ReadingAnnotation
from app.models.readwise import ReadwiseConnection
from app.models.user import User
from app.services.notification_crypto import decrypt_url as decrypt_secret
from app.services.notification_crypto import encrypt_url as encrypt_secret

READWISE_API = "https://readwise.io/api/v2"
READWISE_BATCH_SIZE = 100
EXPORTED_TYPES = ("highlight", "note")


class ReadwiseError(Exception):
    """Readwise could not be reached or rejected the request."""


def user_novels(db: Session, user: User, novel_id: int | None = None) -> list[Novel]:
    library_ids = [library.id for library in user.libraries]
    if not library_ids:
        return []
    query = db.query(Novel).filter(Novel.library_id.in_(library_ids))
    if novel_id is not None:
        query = query.filter(Novel.id == novel_id)
    return query.order_by(Novel.title).all()


def _annotations(db: Session, user: User, novel_id: int) -> list[ReadingAnnotation]:
    rows = (
        db.query(ReadingAnnotation,Chapter)
        .execution_options(include_archived_chapters=True)
        .outerjoin(Chapter,and_(ReadingAnnotation.chapter_id==Chapter.id,
            ReadingAnnotation.chapter_key==Chapter.chapter_key,ReadingAnnotation.novel_id==Chapter.novel_id))
        .filter(
            ReadingAnnotation.user_id == user.id,
            ReadingAnnotation.novel_id == novel_id,
            ReadingAnnotation.annotation_type.in_(EXPORTED_TYPES),
        )
        .order_by(func.coalesce(Chapter.chapter_number,ReadingAnnotation.chapter_number), ReadingAnnotation.position, ReadingAnnotation.created_at)
        .all()
    )
    result=[]
    for row,chapter in rows:
        if not (row.quote or '').strip() and not (row.note or '').strip():continue
        row._export_chapter=chapter_reference(row,chapter)
        result.append(row)
    return result


def chapter_reference(annotation,chapter):
    if chapter is not None and chapter.chapter_key==annotation.chapter_key and chapter.novel_id==annotation.novel_id:
        return SimpleNamespace(id=chapter.chapter_key,chapter_number=chapter.chapter_number,title=chapter.title,
            source_url=chapter.source_url,chapter_key=chapter.chapter_key,archived=chapter.archived,identity_verified=True)
    number=annotation.chapter_number
    label=f'Chapter {number}' if number is not None else 'Preserved chapter'
    return SimpleNamespace(id=('unbound',annotation.chapter_key,number),chapter_number=number,
        title=f'{label} · original reference',source_url=None,chapter_key=annotation.chapter_key,
        archived=None,identity_verified=False)


def _personal(db: Session, user: User, novel_id: int) -> NovelPersonalData | None:
    return db.query(NovelPersonalData).filter(
        NovelPersonalData.user_id == user.id,
        NovelPersonalData.novel_id == novel_id,
    ).first()


def _yaml_value(value) -> str:
    # JSON strings and flow lists are valid YAML, which avoids quoting bugs in titles.
    return "null" if value is None or value == "" else json.dumps(value, ensure_ascii=False)


def story_markdown(novel: Novel, personal: NovelPersonalData | None, annotations: list[ReadingAnnotation]) -> str:
    rating = personal.rating if personal and personal.rating is not None else novel.rating
    tags = sorted(tag.name for tag in novel.tags)
    lines = [
        "---",
        f"title: {_yaml_value(novel.title)}",
        f"author: {_yaml_value(novel.author)}",
        f"site: {_yaml_value(novel.site or novel.novel_site)}",
        f"source_url: {_yaml_value(novel.source_url or novel.url)}",
        f"rating: {_yaml_value(rating)}",
        f"tags: {json.dumps(tags, ensure_ascii=False)}",
        "---",
        "",
        "## Notes",
        "",
        (personal.notes or "").strip() or "_No notes._",
        "",
        "## Highlights",
        "",
    ]

    if not annotations:
        lines.append("_No highlights yet._")

    current_chapter = None
    for annotation in annotations:
        chapter = annotation._export_chapter
        if chapter.id != current_chapter:
            current_chapter = chapter.id
            title = (chapter.title or f"Chapter {chapter.chapter_number}").strip()
            heading = f"[{title}]({chapter.source_url})" if chapter.source_url else title
            lines.extend([f"### {heading}", ""])
        if (annotation.quote or "").strip():
            quote_lines = annotation.quote.strip().splitlines()
            lines.extend(f"> {line}".rstrip() for line in quote_lines)
            lines.append("")
        if (annotation.note or "").strip():
            lines.extend([annotation.note.strip(), ""])

    return "\n".join(lines).rstrip() + "\n"


def _safe_filename(title: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|#^\[\]\x00-\x1f]', " ", title or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return (cleaned or "Untitled")[:120]


def _export_candidates(db: Session, user: User, novel_id: int | None) -> list[tuple[Novel, NovelPersonalData | None, list[ReadingAnnotation]]]:
    result = []
    for novel in user_novels(db, user, novel_id):
        personal = _personal(db, user, novel.id)
        annotations = _annotations(db, user, novel.id)
        has_notes = bool(personal and (personal.notes or "").strip())
        if novel_id is not None or annotations or has_notes:
            result.append((novel, personal, annotations))
    return result


def markdown_documents(db: Session, user: User, novel_id: int | None = None) -> dict[str, str]:
    """Map Obsidian-friendly filenames to Markdown documents, one per story."""
    documents: dict[str, str] = {}
    for novel, personal, annotations in _export_candidates(db, user, novel_id):
        base = _safe_filename(novel.title)
        name = f"{base}.md"
        if name in documents:
            name = f"{base} ({novel.id}).md"
        documents[name] = story_markdown(novel, personal, annotations)
    return documents


def json_export(db: Session, user: User, novel_id: int | None = None) -> list[dict]:
    stories = []
    for novel, personal, annotations in _export_candidates(db, user, novel_id):
        stories.append({
            "novel_id": novel.id,
            "title": novel.title,
            "author": novel.author,
            "site": novel.site or novel.novel_site,
            "source_url": novel.source_url or novel.url,
            "rating": personal.rating if personal and personal.rating is not None else novel.rating,
            "tags": sorted(tag.name for tag in novel.tags),
            "notes": (personal.notes or "").strip() if personal else "",
            "highlights": [
                {
                    "chapter_number": annotation._export_chapter.chapter_number,
                    "chapter_title": annotation._export_chapter.title,
                    "chapter_url": annotation._export_chapter.source_url,
                    "chapter_key": annotation.chapter_key,
                    "source_version": annotation.locator_content_version,
                    "identity_verified": annotation._export_chapter.identity_verified,
                    "chapter_archived": annotation._export_chapter.archived,
                    "type": annotation.annotation_type,
                    "quote": annotation.quote,
                    "note": annotation.note,
                    "created_at": _iso(annotation.created_at),
                }
                for annotation in annotations
            ],
        })
    return stories


def build_zip(documents: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, body in documents.items():
            archive.writestr(name, body.encode("utf-8"))
    return buffer.getvalue()


def get_readwise_token(db: Session, user: User) -> str | None:
    connection = db.query(ReadwiseConnection).filter(ReadwiseConnection.user_id == user.id).first()
    return decrypt_secret(connection.token_encrypted) if connection else None


def save_readwise_token(db: Session, user: User, token: str) -> None:
    connection = db.query(ReadwiseConnection).filter(ReadwiseConnection.user_id == user.id).first()
    if connection is None:
        connection = ReadwiseConnection(user_id=user.id, token_encrypted=encrypt_secret(token))
        db.add(connection)
    else:
        connection.token_encrypted = encrypt_secret(token)
    db.commit()


def delete_readwise_token(db: Session, user: User) -> None:
    db.query(ReadwiseConnection).filter(ReadwiseConnection.user_id == user.id).delete()
    db.commit()


def _post(token: str, path: str, payload: dict | None = None) -> httpx.Response:
    headers = {"Authorization": f"Token {token}"}
    try:
        if payload is None:
            return httpx.get(f"{READWISE_API}{path}", headers=headers, timeout=15)
        return httpx.post(f"{READWISE_API}{path}", headers=headers, json=payload, timeout=30)
    except httpx.HTTPError as exc:
        raise ReadwiseError("Readwise could not be reached") from exc


def verify_readwise_token(token: str) -> bool:
    """Readwise answers 204 for a valid token and 401 otherwise."""
    response = _post(token, "/auth/")
    if response.status_code == 204:
        return True
    if response.status_code == 401:
        return False
    raise ReadwiseError(f"Readwise returned HTTP {response.status_code}")


def send_highlights(token: str, highlights: list[dict]) -> None:
    response = _post(token, "/highlights/", {"highlights": highlights})
    if response.status_code >= 300:
        raise ReadwiseError(f"Readwise returned HTTP {response.status_code}")


def authority(db: Session, user_id: int, expected=None, *, lock=False):
    """Capture request/account identity, never carry an ORM account across I/O."""
    query=db.query(User).filter(User.id==user_id).populate_existing()
    if lock:query=query.with_for_update()
    user=query.first()
    if user is None or user.is_disabled:
        raise HTTPException(401, 'Session ended. Please sign in again.')
    require_current_session(db,user_id)
    value=(user.id,user.storage_id,db.info.get('authenticated_session'))
    if expected is not None and value!=expected:
        raise HTTPException(401, 'Session ended. Please sign in again.')
    return value


def connection_identity(db, user_id, *, lock=False):
    query=db.query(ReadwiseConnection).filter_by(user_id=user_id).populate_existing()
    if lock:query=query.with_for_update()
    row=query.first()
    return None if row is None else tuple(getattr(row,c.name) for c in ReadwiseConnection.__table__.columns)


def _pending_snapshots(db, user, novel_id):
    pending=[]
    for novel,_personal_row,annotations in _export_candidates(db,user,novel_id):
        for annotation in annotations:
            if annotation.exported_at is not None or not (annotation.quote or '').strip():continue
            chapter=annotation._export_chapter
            payload={
                'text':annotation.quote.strip(),'title':novel.title,'author':novel.author or '',
                'source_url':(chapter.source_url or novel.source_url or novel.url or '') if chapter.identity_verified else '',
                'note':(annotation.note or '').strip(),
                **({'location_type':'order','location':chapter.chapter_number} if chapter.identity_verified else {}),
                'category':'books','highlighted_at':_iso(annotation.created_at),
            }
            # Include all original locators/text/version fields, not merely the exported quote.
            identity=tuple(getattr(annotation,c.name) for c in ReadingAnnotation.__table__.columns)
            pending.append((annotation.id,identity,payload))
    return pending


def sync_readwise(db: Session, user: User, token: str, novel_id: int | None = None) -> int:
    """Send detached snapshots; changed or revoked records remain pending."""
    user_id=user.id
    proof=authority(db,user_id)
    connection=connection_identity(db,user_id)
    if connection is None or get_readwise_token(db,user)!=token:
        raise HTTPException(409,'Readwise connection changed. Review and retry.')
    if novel_id is not None and not user_novels(db,user,novel_id):
        raise HTTPException(404,'Novel not found')
    pending=_pending_snapshots(db,user,novel_id)
    db.rollback()
    sent=0
    for start in range(0,len(pending),READWISE_BATCH_SIZE):
        authority(db,user_id,proof)
        if connection_identity(db,user_id)!=connection:
            db.rollback()
            raise HTTPException(409,'Readwise connection changed. Review and retry.')
        current=db.query(User).filter_by(id=user_id).populate_existing().one()
        fresh={row[0]:row for row in _pending_snapshots(db,current,novel_id)}
        batch=[row for row in pending[start:start+READWISE_BATCH_SIZE] if fresh.get(row[0])==row]
        db.rollback()
        if not batch:continue
        send_highlights(token,[row[2] for row in batch])
        sent+=len(batch)
        authority(db,user_id,proof,lock=True)
        if connection_identity(db,user_id,lock=True)!=connection:
            db.rollback()
            raise HTTPException(409,'Readwise connection changed. Review and retry.')
        current=db.query(User).filter_by(id=user_id).populate_existing().one()
        fresh={row[0]:row for row in _pending_snapshots(db,current,novel_id)}
        now=datetime.now(UTC).replace(tzinfo=None)
        for annotation_id,identity,payload in batch:
            if fresh.get(annotation_id)!=(annotation_id,identity,payload):continue
            # CAS in the UPDATE itself prevents a concurrent editor between read and mark.
            predicates=[getattr(ReadingAnnotation,c.name)==value for c,value in zip(ReadingAnnotation.__table__.columns,identity) if not isinstance(c.type,DateTime)]
            db.query(ReadingAnnotation).filter(*predicates).update({'exported_at':now},synchronize_session=False)
        db.commit()
    return sent


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None

