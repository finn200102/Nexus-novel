"""Calibre library interop: read a Calibre ``metadata.db`` upload for import jobs.

The upload is never executed or trusted: it is written to a temp file and
opened with a read-only SQLite connection that only runs SELECT statements.
Each book yields its original story URL (identifiers, a FanFicFare-style URL
custom column, or the comments), plus the personal data Nexus can keep:
tags, a rating (Calibre 0-10 becomes 1-5 stars) and a read flag.
"""

import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass, field
from html import escape
from io import BytesIO
from tempfile import SpooledTemporaryFile
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy.orm import Session

from app.models.import_job import ImportJob, ImportJobItem
from app.models.library import Library
from app.models.novel import Novel
from app.models.novel_personal import NovelPersonalData, NovelUserTag
from app.models.user import User
from app.routers.novel import get_existing_follow, supported_src
from app.services import import_job_service as imports
from app.services import epub_service, user_data_service

SQLITE_MAGIC = b"SQLite format 3\x00"
MAX_CALIBRE_BYTES = 20 * 1024 * 1024
REQUIRED_TABLES = ("books", "identifiers", "tags", "books_tags_link")
# Calibre identifier types that name a story on a supported site.
IDENTIFIER_URLS = {
    "ffnet": "https://www.fanfiction.net/s/{}",
    "ao3": "https://archiveofourown.org/works/{}",
    "rr": "https://www.royalroad.com/fiction/{}",
}
URL_COLUMN_HINTS = ("url", "source", "fanfic")
READ_COLUMN_LABELS = ("read", "is_read", "have_read")
_SAFE_IDENT = re.compile(r"^[A-Za-z0-9_]+$")


class CalibreFormatError(ValueError):
    """The upload is not a Calibre metadata.db."""


@dataclass
class CalibreBook:
    book_id: int
    title: str
    url: str | None = None
    tags: list[str] = field(default_factory=list)
    rating: int | None = None  # Nexus stars, 1-5
    read: bool | None = None


def stars_from_calibre(rating: int | None) -> int | None:
    """Calibre rates 0-10 (two per star); 0 means unrated."""
    if not rating or rating <= 0:
        return None
    return min(5, (min(rating, 10) + 1) // 2)


def calibre_from_stars(stars: int | None) -> int | None:
    return stars * 2 if stars else None


def _check_tables(conn: sqlite3.Connection) -> None:
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if not all(table in names for table in REQUIRED_TABLES):
        raise CalibreFormatError("not a Calibre metadata.db (books, identifiers and tags tables are required)")


def _custom_columns(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "custom_columns" not in names:
        return []
    rows = conn.execute("SELECT id, label, datatype FROM custom_columns").fetchall()
    return [(int(cid), str(label), str(dtype)) for cid, label, dtype in rows if _SAFE_IDENT.match(str(label))]


def _column_values(conn: sqlite3.Connection, column_id: int) -> dict[int, object]:
    table = f"custom_column_{int(column_id)}"  # ids are integers from custom_columns, never user text
    return {int(book): value for book, value in conn.execute(f"SELECT book, value FROM {table}")}


def read_calibre_library(data: bytes) -> list[CalibreBook]:
    """Books of a Calibre metadata.db, with source URL and personal data."""
    if len(data) > MAX_CALIBRE_BYTES:
        raise CalibreFormatError("metadata.db is larger than 20 MB")
    if not data.startswith(SQLITE_MAGIC):
        raise CalibreFormatError("not a SQLite database")
    handle, path = tempfile.mkstemp(suffix=".db")
    try:
        with os.fdopen(handle, "wb") as temp:
            temp.write(data)
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            conn.execute("PRAGMA query_only = ON")
            _check_tables(conn)
            return _collect(conn)
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise CalibreFormatError(f"cannot read metadata.db: {exc}") from exc
    finally:
        os.unlink(path)


def _collect(conn: sqlite3.Connection) -> list[CalibreBook]:
    books = {int(bid): CalibreBook(book_id=int(bid), title=str(title or "")) for bid, title in conn.execute("SELECT id, title FROM books")}
    identifiers: dict[int, dict[str, str]] = {}
    for book, kind, value in conn.execute("SELECT book, type, val FROM identifiers"):
        identifiers.setdefault(int(book), {})[str(kind).lower()] = str(value or "")
    comments = {int(book): str(text or "") for book, text in conn.execute("SELECT book, text FROM comments")} if _has(conn, "comments") else {}
    tags: dict[int, list[str]] = {}
    for book, name in conn.execute("SELECT l.book, t.name FROM books_tags_link l JOIN tags t ON t.id = l.tag ORDER BY t.name"):
        tags.setdefault(int(book), []).append(str(name))
    ratings = {}
    if _has(conn, "ratings") and _has(conn, "books_ratings_link"):
        ratings = {int(book): int(value) for book, value in conn.execute(
            "SELECT l.book, r.rating FROM books_ratings_link l JOIN ratings r ON r.id = l.rating")}

    url_columns, read_column = [], None
    for column_id, label, dtype in _custom_columns(conn):
        if dtype == "bool" and label.lower() in READ_COLUMN_LABELS:
            read_column = _column_values(conn, column_id)
        elif dtype in ("text", "comments") and any(hint in label.lower() for hint in URL_COLUMN_HINTS):
            url_columns.append(_column_values(conn, column_id))

    result = []
    for book_id, book in books.items():
        book.tags = tags.get(book_id, [])
        book.rating = stars_from_calibre(ratings.get(book_id))
        if read_column is not None and book_id in read_column and read_column[book_id] is not None:
            book.read = bool(read_column[book_id])
        book.url = _source_url(book_id, identifiers.get(book_id, {}), url_columns, comments.get(book_id, ""))
        result.append(book)
    return result


def _has(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def _source_url(book_id: int, identifiers: dict[str, str], url_columns: list[dict], comments: str) -> str | None:
    candidates: list[str] = []
    if identifiers.get("url"):
        candidates.append(identifiers["url"])
    for kind, template in IDENTIFIER_URLS.items():
        if identifiers.get(kind):
            candidates.append(template.format(identifiers[kind]))
    for values in url_columns:
        if values.get(book_id):
            candidates.extend(imports.extract_urls(str(values[book_id])))
    candidates.extend(imports.extract_urls(comments))
    supported = [url for url in candidates if supported_src(url)]
    return supported[0] if supported else None


def calibre_entries(books: list[CalibreBook]) -> tuple[list[dict], dict[str, dict]]:
    """Import-job entries for the books, and per-URL personal data for the job."""
    entries, personal = [], {}
    for book in books:
        if not book.url:
            entries.append({"label": book.title, "title": book.title or None, "status": "unsupported",
                            "reason": "no supported source URL in identifiers, columns or comments"})
            continue
        entries.append({"label": book.title, "title": book.title or None, "url": book.url})
        personal[imports.url_key(book.url)] = {"tags": book.tags, "rating": book.rating, "read": book.read}
    return entries, personal


def apply_calibre_meta(db: Session, job: ImportJob, item: ImportJobItem) -> None:
    """Copy a Calibre book's tags, rating and read flag onto its linked novel."""
    if job.source != "calibre" or item.novel_id is None or item.status not in ("linked", "duplicate"):
        return
    meta = ((job.params or {}).get("calibre") or {}).get(imports.url_key(item.url))
    if not meta:
        return
    user = db.get(User, job.user_id)
    novel = db.get(Novel, item.novel_id)
    if user is None or novel is None:
        return
    user_data_service._apply_personal(db, user, novel, SimpleNamespace(
        notes=None, rating=meta.get("rating"), user_tags=meta.get("tags") or []))
    if meta.get("read") is True:
        user_data_service._apply_follow(db, user, novel, SimpleNamespace(follow_state="completed", followed_at=None))
    elif meta.get("read") is False and get_existing_follow(db, user.id, novel) is None:
        user_data_service._apply_follow(db, user, novel, SimpleNamespace(follow_state="plan_to_read", followed_at=None))


def _calibre_opf_fields(novel: Novel, tags: list[str], stars: int | None) -> str:
    """Dublin Core and Calibre meta elements that Calibre reads on "Add books"."""
    fields = []
    if novel.url:
        fields.append(f"<dc:source>{escape(novel.url)}</dc:source>")
    fields.extend(f"<dc:subject>{escape(tag)}</dc:subject>" for tag in tags)
    if stars:
        fields.append(f'<meta name="calibre:rating" content="{calibre_from_stars(stars)}"/>')
    return "".join(fields)


def _with_calibre_metadata(epub: bytes, novel: Novel, tags: list[str], stars: int | None) -> bytes:
    out = BytesIO()
    with ZipFile(BytesIO(epub)) as source, ZipFile(out, "w") as target:
        for info in source.infolist():
            content = source.read(info.filename)
            if info.filename.endswith(".opf"):
                text = content.decode("utf-8")
                text = text.replace("</metadata>", _calibre_opf_fields(novel, tags, stars) + "</metadata>", 1)
                content = text.encode("utf-8")
            target.writestr(info.filename, content, compress_type=info.compress_type)
    return out.getvalue()


def export_calibre_zip(db: Session, user: User) -> SpooledTemporaryFile:
    """A zip of the user's built EPUBs with Calibre metadata; rewound for reading.

    Novels without a downloaded chapter are skipped.
    """
    novels = (
        db.query(Novel)
        .join(Library, Library.id == Novel.library_id)
        .filter(Library.user_id == user.id)
        .order_by(Novel.id)
        .all()
    )
    out = SpooledTemporaryFile(max_size=8 * 1024 * 1024)
    with ZipFile(out, "w", ZIP_DEFLATED) as archive:
        for novel in novels:
            try:
                built = epub_service.ensure_build(db, novel)
            except epub_service.NoDownloadedChapters:
                continue
            tags = [row.tag for row in db.query(NovelUserTag).filter(
                NovelUserTag.user_id == user.id, NovelUserTag.novel_id == novel.id).order_by(NovelUserTag.tag)]
            personal = db.query(NovelPersonalData).filter(
                NovelPersonalData.user_id == user.id, NovelPersonalData.novel_id == novel.id).first()
            slug = re.sub(r"[^A-Za-z0-9]+", "-", novel.title or "").strip("-")[:60] or "novel"
            archive.writestr(f"{novel.id}-{slug}.epub", _with_calibre_metadata(
                built.path.read_bytes(), novel, tags, personal.rating if personal else None))
    out.seek(0)
    return out
