"""Builds EPUB files from downloaded chapters and caches them on disk.

A build is keyed by novel id and a fingerprint of the chapters it contains
(ids, numbers, titles and update times), so it is rebuilt when a chapter is
added or changed. Every build also records KOReader's partial MD5 of the file,
which is how sync progress is matched back to a novel.
"""

import hashlib
import json
import os
from dataclasses import dataclass
from html import escape
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from sqlalchemy.orm import Session

from app.models.chapter import Chapter, ContentStatus
from app.models.ereader import EpubBuild
from app.models.novel import Novel
from config.settings import settings

EPUB_DIR_NAME = "epub"


class NoDownloadedChapters(Exception):
    """The novel has no chapter content to put in a book."""


@dataclass(frozen=True)
class BuiltEpub:
    build: EpubBuild
    path: Path


def downloaded_chapters(db: Session, novel_id: int) -> list[Chapter]:
    return (
        db.query(Chapter)
        .filter(
            Chapter.novel_id == novel_id,
            Chapter.content_status == ContentStatus.PRESENT,
            Chapter.content.isnot(None),
        )
        .order_by(Chapter.chapter_number.asc())
        .all()
    )


def _downloaded_chapter_rows(db: Session, novel_id: int) -> list:
    """Chapter metadata only, so freshness checks do not load chapter bodies."""
    return (
        db.query(Chapter.id, Chapter.chapter_number, Chapter.title, Chapter.updated_at)
        .filter(
            Chapter.novel_id == novel_id,
            Chapter.content_status == ContentStatus.PRESENT,
            Chapter.content.isnot(None),
        )
        .order_by(Chapter.chapter_number.asc())
        .all()
    )


def fingerprint(novel: Novel, rows: list) -> str:
    payload = {
        "novel": [novel.id, novel.title or "", novel.author or ""],
        "chapters": [[row[0], row[1], row[2] or "", str(row[3])] for row in rows],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _sampled_md5(data: bytes, first_offset: int) -> str:
    digest = hashlib.md5()
    for i in range(-1, 11):
        offset = first_offset if i == -1 else 1024 << (2 * i)
        if offset >= len(data):
            break
        digest.update(data[offset : offset + 1024])
    return digest.hexdigest()


def partial_md5(data: bytes) -> str:
    """KOReader's ``util.partialMD5`` with the first sample at offset 256."""
    return _sampled_md5(data, 256)


def partial_md5_lua(data: bytes) -> str:
    """The same sampling with the first sample at offset 0, as LuaJIT computes it."""
    return _sampled_md5(data, 0)


def render_epub(novel: Novel, chapters: list[Chapter]) -> bytes:
    book_title = escape(novel.title or "Nexus Novel")
    author = escape(novel.author or "Unknown author")
    book_id = f"nexus-novel-{novel.id}"
    package = BytesIO()
    with ZipFile(package, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr("META-INF/container.xml", """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""")
        manifest = []
        spine = []
        for index, chapter in enumerate(chapters, start=1):
            item_id = f"chapter-{index}"
            filename = f"OEBPS/{item_id}.xhtml"
            paragraphs = "".join(f"<p>{escape(line)}</p>" for line in (chapter.content or "").splitlines() if line.strip())
            if not paragraphs:
                paragraphs = f"<p>{escape(chapter.content or '')}</p>"
            xhtml = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{escape(chapter.title or f'Chapter {chapter.chapter_number}')}</title></head>
<body><h1>{escape(chapter.title or f'Chapter {chapter.chapter_number}')}</h1>{paragraphs}</body></html>"""
            archive.writestr(filename, xhtml, compress_type=ZIP_DEFLATED)
            manifest.append(f'<item id="{item_id}" href="{item_id}.xhtml" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="{item_id}"/>')
        opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book-id">{book_id}</dc:identifier><dc:title>{book_title}</dc:title><dc:creator>{author}</dc:creator><dc:language>en</dc:language></metadata>
<manifest>{''.join(manifest)}</manifest><spine>{''.join(spine)}</spine></package>"""
        archive.writestr("OEBPS/content.opf", opf, compress_type=ZIP_DEFLATED)
    return package.getvalue()


def epub_dir() -> Path:
    return Path(settings.DOWNLOAD_PATH) / EPUB_DIR_NAME


def ensure_build(db: Session, novel: Novel) -> BuiltEpub:
    """Return the current EPUB for ``novel``, building it when the chapters changed.

    Older cached files for the novel are deleted; their EpubBuild rows stay so
    progress from a copy someone already downloaded can still be matched.
    """
    rows = _downloaded_chapter_rows(db, novel.id)
    if not rows:
        raise NoDownloadedChapters()
    fp = fingerprint(novel, rows)
    directory = epub_dir()
    file_name = f"{novel.id}-{fp[:16]}.epub"
    path = directory / file_name

    build = db.query(EpubBuild).filter(EpubBuild.novel_id == novel.id, EpubBuild.fingerprint == fp).first()
    if build is not None and path.is_file():
        if build.partial_md5_lua is None:
            # Builds made before the LuaJIT variant existed are backfilled from the file.
            build.partial_md5_lua = partial_md5_lua(path.read_bytes())
            db.commit()
        return BuiltEpub(build=build, path=path)

    chapters = downloaded_chapters(db, novel.id)
    data = render_epub(novel, chapters)
    directory.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)
    for stale in directory.glob(f"{novel.id}-*.epub"):
        if stale != path:
            stale.unlink(missing_ok=True)

    if build is None:
        build = EpubBuild(novel_id=novel.id, fingerprint=fp)
        db.add(build)
    build.partial_md5 = partial_md5(data)
    build.partial_md5_lua = partial_md5_lua(data)
    build.size_bytes = len(data)
    build.file_name = file_name
    build.spine = [chapter.chapter_number for chapter in chapters]
    db.commit()
    return BuiltEpub(build=build, path=path)
