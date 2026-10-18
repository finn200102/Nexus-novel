"""Import a bounded EPUB into its owner's library without contacting a source."""
import base64
import hashlib
import json
import io
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile
from urllib.parse import unquote

from app.models.chapter import Chapter, ContentStatus
from app.models.novel import Novel
from app.services.chapter_document import from_html
from app.services.content_limit_service import item_allowed, RESTRICTED_MESSAGE

MAX_MEMBER = 8 * 1024 * 1024
MAX_EXPANDED = 80 * 1024 * 1024


def _xml(data):
    declarations = data.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
        raise ValueError("EPUB XML declarations are not supported")
    return ET.fromstring(data)


def _path(base, href):
    value = posixpath.normpath(posixpath.join(base, unquote(href.split("#")[0])))
    if value.startswith(("../", "/")) or value == ".." or "\\" in value:
        raise ValueError("EPUB contains an unsafe member path")
    return value


def read_epub(data):
    try:
        archive = ZipFile(io.BytesIO(data))
    except BadZipFile as exc:
        raise ValueError("File is not a valid EPUB archive") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > 10_000 or sum(member.file_size for member in infos) > MAX_EXPANDED:
            raise ValueError("EPUB expands beyond the import limit")

        def read(name):
            if archive.getinfo(name).file_size > MAX_MEMBER:
                raise ValueError("An EPUB member exceeds the import limit")
            return archive.read(name)

        try:
            container = _xml(read("META-INF/container.xml"))
            rootfile = container.find(".//{*}rootfile")
            if rootfile is None:
                raise ValueError("EPUB has no package document")
            opf_path = _path("", rootfile.attrib["full-path"])
            opf = _xml(read(opf_path))
            base = posixpath.dirname(opf_path)
            metadata = opf.find("{*}metadata")
            if metadata is None:
                raise ValueError("EPUB has no metadata")
            title = metadata.findtext("{*}title") or "Imported book"
            author = metadata.findtext("{*}creator") or "Unknown author"
            tags = [(tag.text or "").strip() for tag in metadata.findall("{*}subject")]
            manifest = {item.attrib["id"]: item for item in opf.findall("{*}manifest/{*}item")}
            cover = None
            cover_id = next((node.get("content") for node in metadata.findall("{*}meta") if node.get("name") == "cover"), None)
            cover_item = next((item for item in manifest.values() if "cover-image" in (item.get("properties") or "").split()), manifest.get(cover_id))
            if cover_item is not None:
                blob = read(_path(base, cover_item.attrib["href"]))
                mime = "image/png" if blob.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg" if blob.startswith(b"\xff\xd8\xff") else None
                if mime and len(blob) <= 2_000_000:
                    cover = {"media_type": mime, "data": blob}
            spine = opf.findall("{*}spine/{*}itemref")
            if not spine or len(spine) > 2_000:
                raise ValueError("EPUB must contain between 1 and 2,000 spine items")
            chapters = []
            document_bytes = 0
            for entry in spine:
                if entry.get("linear") == "no":
                    continue
                item = manifest[entry.attrib["idref"]]
                if item.get("media-type") not in {"application/xhtml+xml", "text/html"}:
                    continue
                member_path = _path(base, item.attrib["href"])
                page = read(member_path).decode("utf-8", "replace")

                def image(match):
                    href = match.group(2)
                    if ":" in href or href.startswith("//"):
                        return match.group(0)
                    path = _path(posixpath.dirname(member_path), href)
                    try:
                        blob = read(path)
                    except KeyError:
                        return match.group(0)
                    mime = "image/png" if blob.startswith(b"\x89PNG\r\n\x1a\n") else "image/jpeg" if blob.startswith(b"\xff\xd8\xff") else "image/gif" if blob.startswith((b"GIF87a", b"GIF89a")) else None
                    if not mime or len(blob) > 2_000_000:
                        return match.group(0)
                    return f'{match.group(1)}"data:{mime};base64,{base64.b64encode(blob).decode()}"'

                page = re.sub(r'(\bsrc\s*=\s*)["\']([^"\']+)["\']', image, page, flags=re.I)
                document = from_html(page)
                document_bytes += len(json.dumps(document, ensure_ascii=False).encode())
                if document_bytes > MAX_EXPANDED:
                    raise ValueError("EPUB content exceeds the import limit after embedding its images")
                if not document["blocks"]:
                    continue
                heading = next((block["text"] for block in document["blocks"] if block["kind"].startswith("h")), None)
                chapters.append({"title": (heading or f"Chapter {len(chapters) + 1}")[:255], "document": document})
            if not chapters:
                raise ValueError("EPUB contains no readable chapters")
            return {"title": title[:255], "author": author[:255], "tags": tags, "chapters": chapters, "cover": cover}
        except (KeyError, ET.ParseError, UnicodeError) as exc:
            raise ValueError("EPUB package or spine is malformed") from exc


def import_local_epub(db, user, library, data):
    book = read_epub(data)
    from fastapi import HTTPException
    from app.models import User,Library
    from app.auth.dependencies import require_current_session
    from app.services.chapter_identity_service import sqlite_transaction
    sqlite_transaction(db,write=True)
    fresh=db.query(User).filter_by(id=user.id).populate_existing().with_for_update().first()
    if fresh is None or fresh.is_disabled:raise HTTPException(401,'Account is unavailable')
    require_current_session(db,user.id)
    if db.query(Library).filter_by(id=library.id,user_id=user.id).populate_existing().with_for_update().first() is None:raise HTTPException(404,'Library not found')
    if not item_allowed(user, {"tags": book["tags"], "content_rating": "not_rated"}):
        return {"status": "restricted", "reason": RESTRICTED_MESSAGE}
    url = "nexus-local:epub:" + hashlib.sha256(data).hexdigest()
    existing = db.query(Novel).filter_by(library_id=library.id, url=url).populate_existing().with_for_update().first()
    placeholder=existing is not None and existing.novel_site=='local' and existing.scrape_status=='awaiting_original'
    if placeholder:
        # Do not overwrite any retained original/archive even if a stale marker
        # survived an older import. Exact-byte SHA and owner library are required.
        has_original=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(novel_id=existing.id).first() is not None
        placeholder=not has_original
    if existing is not None and not placeholder:
        return {"status": "duplicate", "novel_id": existing.id, "title": existing.title, "reason": "Already in this library"}
    if placeholder:
        novel=existing
        novel.author=novel.author or book['author']
        novel.scrape_status='completed';novel.scrape_error=None
        novel.num_chapters=len(book['chapters']);novel.chapter_count=len(book['chapters'])
    else:
        novel = Novel(title=book["title"], author=book["author"], library_id=library.id, url=url,
                      novel_site="local", site="local", scrape_status="completed", num_chapters=len(book["chapters"]), chapter_count=len(book["chapters"]))
        db.add(novel)
        db.flush()
    if book["cover"] and not novel.cover_image:
        from app.models.local_cover import LocalBookCover
        novel.cover_image = f"nexus-cover:{novel.id}"
        db.add(LocalBookCover(novel_id=novel.id, **book["cover"]))
    for number, chapter in enumerate(book["chapters"], 1):
        db.add(Chapter(novel_id=novel.id, chapter_number=number, title=chapter["title"],
                       content=chapter["document"]["plain_text"], document=chapter["document"], content_status=ContentStatus.PRESENT))
    db.flush()
    return {"status": "linked", "novel_id": novel.id, "title": novel.title, "reason": "Imported locally; no source requests made"}
