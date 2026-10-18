"""Builds EPUB files from downloaded chapters and caches them on disk.

A build is keyed by its owned source, reading run and immutable chapter
identities plus strong hashes of the rendered source. Old files remain private
exports; their stored spine never follows a replacement numeric address. Every build also records KOReader's partial MD5 of the file,
which is how sync progress is matched back to a novel.
"""

import hashlib
import json
import os
import base64
import re
from datetime import UTC, datetime
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
            Chapter.archived.is_(False),
            Chapter.content_status == ContentStatus.PRESENT,
            Chapter.content.isnot(None),
        )
        .order_by(Chapter.chapter_number.asc())
        .populate_existing()
        .all()
    )


def _downloaded_chapter_rows(db: Session, novel_id: int) -> list:
    """Stream strong source hashes; retain only small immutable spine metadata."""
    from app.services.ereader_identity_service import digest
    from app.services.chapter_identity_service import source_version
    rows=[]
    query=db.query(Chapter).filter(Chapter.novel_id==novel_id,Chapter.archived.is_(False),
        Chapter.content_status==ContentStatus.PRESENT,Chapter.content.isnot(None)).order_by(Chapter.chapter_number,Chapter.id).populate_existing().yield_per(32)
    for chapter in query:
        rows.append((chapter.id,chapter.chapter_number,chapter.title,chapter.updated_at,chapter.chapter_key,source_version(chapter),digest(chapter)))
    return rows


def fingerprint(novel: Novel, rows: list) -> str:
    from app.services.chapter_identity_service import manifest_state
    from app.services.ereader_identity_service import source_snapshot
    from sqlalchemy.orm import object_session
    db=object_session(novel)
    state=manifest_state(db,novel.id)
    from app.services.reading_run_service import current_run
    from app.models.library import Library
    from app.models.user import User
    user_id,storage_id=db.query(Library.user_id,User.storage_id).join(User,User.id==Library.user_id).filter(Library.id==novel.library_id).one()
    run=current_run(db,user_id,novel.id)
    cover=getattr(novel,"local_cover",None)
    cover_identity=[cover.media_type,hashlib.sha256(cover.data).hexdigest()] if cover else None
    payload={"cover":cover_identity,"format_version":"nexus-epub-v3-immutable-spine","novel":[novel.id,novel.title or '',novel.author or ''],
        "owner":storage_id,"source":source_snapshot(db,novel),"epoch":state.manifest_epoch,"run":run.run_key if run and (run.requires_run_key or run.ordinal!=1) else "initial",
        "chapters":[[row[0],row[1],row[2] or '',row[4],row[5],row[6]] for row in rows]}
    return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()


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


def render_epub(novel: Novel, chapters: list[Chapter], *, language: str = "en", identifier: str | None = None) -> bytes:
    book_title = escape(novel.title or "Nexus Novel")
    author = escape(novel.author or "Unknown author")
    book_id = escape(identifier or f"nexus-novel-{novel.id}")
    package = BytesIO()
    with ZipFile(package, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=ZIP_STORED)
        archive.writestr("META-INF/container.xml", """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>""")
        manifest = ['<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>']
        spine = []
        navigation = []
        assets = set()
        cover = getattr(novel, "local_cover", None)
        if cover:
            suffix = "png" if cover.media_type == "image/png" else "jpg"
            archive.writestr(f"OEBPS/cover.{suffix}", cover.data, compress_type=ZIP_DEFLATED)
            manifest.append(f'<item id="cover" href="cover.{suffix}" media-type="{cover.media_type}" properties="cover-image"/>')
        for index, chapter in enumerate(chapters, start=1):
            item_id = f"chapter-{index}"
            filename = f"OEBPS/{item_id}.xhtml"
            from app.services.chapter_document import from_html, from_text
            blocks = chapter.document.get("blocks", []) if getattr(chapter, "document", None) else from_text(chapter.content or "")["blocks"]
            sections = []
            for block in blocks:
                approved = from_html(block.get("html", ""))
                block_id = block.get("id", "")
                if not re.fullmatch(r"b-[a-f0-9]{24}-[0-9]+", block_id):
                    block_id = approved["blocks"][0]["id"] if approved["blocks"] else ""
                role = ' data-nexus-role="author_note"' if block.get("role") == "author_note" else ""
                sections.append(f'<section id="{escape(block_id, quote=True)}"{role}>' + "".join(item["html"] for item in approved["blocks"]) + '</section>')
            paragraphs = "".join(sections)
            def asset(match):
                media_type, encoded = match.group(1), match.group(2)
                name = f"image-{hashlib.sha256(encoded.encode()).hexdigest()[:24]}"
                suffix = {"png": "png", "jpeg": "jpg", "gif": "gif", "webp": "webp"}[media_type]
                if name not in assets:
                    assets.add(name)
                    archive.writestr(f"OEBPS/{name}.{suffix}", base64.b64decode(encoded), compress_type=ZIP_DEFLATED)
                    manifest.append(f'<item id="{name}" href="{name}.{suffix}" media-type="image/{media_type}"/>')
                return f'src="{name}.{suffix}"'
            paragraphs = re.sub(r'src="data:image/(png|jpeg|gif|webp);base64,([A-Za-z0-9+/=]+)"', asset, paragraphs)
            if not paragraphs:
                paragraphs = f"<p>{escape(chapter.content or '')}</p>"
            xhtml = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{escape(chapter.title or f'Chapter {chapter.chapter_number}')}</title></head>
<body><h1>{escape(chapter.title or f'Chapter {chapter.chapter_number}')}</h1>{paragraphs}</body></html>"""
            archive.writestr(filename, xhtml, compress_type=ZIP_DEFLATED)
            manifest.append(f'<item id="{item_id}" href="{item_id}.xhtml" media-type="application/xhtml+xml"/>')
            spine.append(f'<itemref idref="{item_id}"/>')
            navigation.append(f'<li><a href="{item_id}.xhtml">{escape(chapter.title or f"Chapter {chapter.chapter_number}")}</a></li>')
        archive.writestr("OEBPS/nav.xhtml", '<?xml version="1.0" encoding="utf-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
            '<head><title>Contents</title></head><body><nav epub:type="toc"><h1>Contents</h1><ol>'
            + "".join(navigation) + '</ol></nav></body></html>', compress_type=ZIP_DEFLATED)
        modified = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="book-id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="book-id">{book_id}</dc:identifier><dc:title>{book_title}</dc:title><dc:creator>{author}</dc:creator><dc:language>{escape(language)}</dc:language><meta property="dcterms:modified">{modified}</meta></metadata>
<manifest>{''.join(manifest)}</manifest><spine>{''.join(spine)}</spine></package>"""
        archive.writestr("OEBPS/content.opf", opf, compress_type=ZIP_DEFLATED)
    return package.getvalue()


def epub_dir() -> Path:
    return Path(settings.DOWNLOAD_PATH) / EPUB_DIR_NAME


def ensure_build(db: Session, novel: Novel) -> BuiltEpub:
    """Return the current EPUB for ``novel``, building it when the chapters changed.

    Older cached files and their EpubBuild rows stay so
    progress from a copy someone already downloaded can still be matched.
    """
    from app.models.library import Library
    from app.services.ereader_identity_service import owner
    from app.services.chapter_identity_service import manifest_state,source_version
    from app.services.reading_run_service import current_run
    library=db.get(Library,novel.library_id)
    if library is None:
        from fastapi import HTTPException
        raise HTTPException(404,"Story not found")
    user,novel=owner(db,library.user_id,novel.id)
    db.query(Chapter.id).filter(Chapter.novel_id==novel.id,Chapter.archived.is_(False)).order_by(Chapter.id).with_for_update().all()
    state=manifest_state(db,novel.id,lock=True)
    rows = _downloaded_chapter_rows(db, novel.id)
    if not rows:
        raise NoDownloadedChapters()
    fp = fingerprint(novel, rows)
    directory = Path(settings.DOWNLOAD_PATH).resolve()/EPUB_DIR_NAME
    if directory.is_symlink():raise ValueError('The private EPUB directory must not be a symbolic link')
    file_name = f"{novel.id}-{fp}.epub"
    path = directory / file_name

    build = db.query(EpubBuild).filter(EpubBuild.novel_id == novel.id, EpubBuild.fingerprint == fp).first()
    if build is not None and path.is_file():
        if build.partial_md5_lua is None:
            # Builds made before the LuaJIT variant existed are backfilled from the file.
            build.partial_md5_lua = partial_md5_lua(path.read_bytes())
        db.commit()  # release account/chapter locks even when the file is cached
        return BuiltEpub(build=build, path=path)

    chapters = downloaded_chapters(db, novel.id)
    data = render_epub(novel, chapters,identifier=f"nexus-novel-{novel.id}-build-{fp}")
    directory.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)

    if build is None:
        build = EpubBuild(novel_id=novel.id, fingerprint=fp)
        db.add(build)
    build.partial_md5 = partial_md5(data)
    build.partial_md5_lua = partial_md5_lua(data)
    build.size_bytes = len(data)
    build.file_name = file_name
    from app.services.ereader_identity_service import digest
    build.spine = [chapter.chapter_number for chapter in chapters]
    build.spine_identity=[dict(chapter_key=chapter.chapter_key,chapter_number=chapter.chapter_number,
        source_version=source_version(chapter),body_sha256=digest(chapter)) for chapter in chapters]
    from app.services.ereader_identity_service import source_snapshot
    build.source_snapshot=source_snapshot(db,novel)
    build.owner_storage_id=user.storage_id;build.manifest_epoch=state.manifest_epoch
    run=current_run(db,user.id,novel.id)
    build.reading_run_key=run.run_key if run else None
    db.commit()
    return BuiltEpub(build=build, path=path)



def cached_path(build):
    directory=Path(settings.DOWNLOAD_PATH).resolve()/EPUB_DIR_NAME
    if Path(build.file_name).name!=build.file_name or directory.is_symlink():
        raise FileNotFoundError('Unsafe private EPUB path')
    path=directory/build.file_name
    if path.is_symlink() or not path.is_file():raise FileNotFoundError('Private EPUB file unavailable')
    return path
