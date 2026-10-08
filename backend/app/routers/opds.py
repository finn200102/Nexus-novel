"""OPDS 1.2 (Atom) catalog for e-reader apps.

Authentication is HTTP Basic with the username and an OPDS app password. Links
are relative to the feed's own location, so the feeds work the same behind the
``/api`` prefix that nginx strips.
"""

import base64
import posixpath
import re
from datetime import UTC, datetime
from html import unescape
from email.utils import format_datetime, parsedate_to_datetime
from urllib.parse import urlencode
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import false, or_
from sqlalchemy.orm import Session

from app.models.chapter import Chapter, ContentStatus
from app.models.follow import UserNovelFollow
from app.models.library import Library
from app.models.novel import Novel
from app.models.user import User
from app.services import app_password_service, epub_service
from config.database import get_db

ATOM_NS = "http://www.w3.org/2005/Atom"
OPENSEARCH_NS = "http://a9.com/-/spec/opensearch/1.1/"
ET.register_namespace("", ATOM_NS)
ET.register_namespace("os", OPENSEARCH_NS)

NAV_TYPE = "application/atom+xml;profile=opds-catalog;kind=navigation"
ACQ_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"
SEARCH_TYPE = "application/opensearchdescription+xml"
EPUB_TYPE = "application/epub+zip"
PAGE_SIZE = 25
SUMMARY_LIMIT = 600

router = APIRouter(
    prefix="/opds",
    tags=["opds"],
    responses={404: {"description": "Not found"}},
)


def get_opds_user(request: Request, db: Session = Depends(get_db)) -> User:
    challenge = {"WWW-Authenticate": 'Basic realm="Nexus"'}
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("basic "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required", headers=challenge)
    try:
        decoded = base64.b64decode(header[6:].strip()).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required", headers=challenge)
    username, separator, password = decoded.partition(":")
    if not separator:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required", headers=challenge)
    try:
        return app_password_service.authenticate_basic(db, request, username, password)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_401_UNAUTHORIZED:
            raise HTTPException(status_code=401, detail=exc.detail, headers=challenge)
        raise


# ---- link helpers -------------------------------------------------------

def _href(request: Request, target: str, params: dict | None = None) -> str:
    """A reference relative to this request's directory, so /api prefixes work."""
    path = request.url.path
    base = path if path.endswith("/") else posixpath.dirname(path) + "/"
    relative = posixpath.relpath(target, base)
    if target.endswith("/") and not relative.endswith("/"):
        relative += "/"
    if params:
        relative += "?" + urlencode({key: value for key, value in params.items() if value not in (None, "")})
    return relative


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stamp(value: datetime | None) -> str:
    if value is None:
        return _now()
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _link(parent: ET.Element, rel: str, href: str, type_: str | None = None, title: str | None = None) -> None:
    attrs = {"rel": rel, "href": href}
    if type_:
        attrs["type"] = type_
    if title:
        attrs["title"] = title
    ET.SubElement(parent, f"{{{ATOM_NS}}}link", attrs)


def _feed(request: Request, *, feed_id: str, title: str, kind: str, updated: str | None = None) -> ET.Element:
    feed = ET.Element(f"{{{ATOM_NS}}}feed")
    ET.SubElement(feed, f"{{{ATOM_NS}}}id").text = feed_id
    ET.SubElement(feed, f"{{{ATOM_NS}}}title").text = title
    ET.SubElement(feed, f"{{{ATOM_NS}}}updated").text = updated or _now()
    ET.SubElement(feed, f"{{{ATOM_NS}}}author").append(_text_el("name", "Nexus"))
    _link(feed, "self", _href(request, request.url.path, dict(request.query_params)), NAV_TYPE if kind == "navigation" else ACQ_TYPE)
    _link(feed, "start", _href(request, "/opds/"), NAV_TYPE)
    _link(feed, "search", _href(request, "/opds/opensearch.xml"), SEARCH_TYPE)
    return feed


def _text_el(tag: str, text: str) -> ET.Element:
    element = ET.Element(f"{{{ATOM_NS}}}{tag}")
    element.text = text
    return element


def _nav_entry(feed: ET.Element, request: Request, *, entry_id: str, title: str, target: str, summary: str) -> None:
    entry = ET.SubElement(feed, f"{{{ATOM_NS}}}entry")
    ET.SubElement(entry, f"{{{ATOM_NS}}}id").text = entry_id
    ET.SubElement(entry, f"{{{ATOM_NS}}}title").text = title
    ET.SubElement(entry, f"{{{ATOM_NS}}}updated").text = _now()
    content = ET.SubElement(entry, f"{{{ATOM_NS}}}content", {"type": "text"})
    content.text = summary
    _link(entry, "subsection", _href(request, target), ACQ_TYPE)


def _summary(text: str | None) -> str:
    plain = re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()
    return plain[:SUMMARY_LIMIT]


def _novel_entries(feed: ET.Element, request: Request, novels: list[Novel], with_epub: set[int]) -> None:
    for novel in novels:
        entry = ET.SubElement(feed, f"{{{ATOM_NS}}}entry")
        ET.SubElement(entry, f"{{{ATOM_NS}}}id").text = f"urn:nexus:novel:{novel.id}"
        ET.SubElement(entry, f"{{{ATOM_NS}}}title").text = novel.title or "Untitled"
        ET.SubElement(entry, f"{{{ATOM_NS}}}updated").text = _stamp(novel.updated_at or novel.created_at)
        author = ET.SubElement(entry, f"{{{ATOM_NS}}}author")
        author.append(_text_el("name", novel.author or "Unknown author"))
        if novel.description:
            ET.SubElement(entry, f"{{{ATOM_NS}}}summary", {"type": "text"}).text = _summary(novel.description)
        if novel.img_url and novel.img_url.startswith(("http://", "https://")):
            _link(entry, "http://opds-spec.org/image", novel.img_url, "image/jpeg")
        if novel.id in with_epub:
            _link(entry, "http://opds-spec.org/acquisition", _href(request, f"/opds/novels/{novel.id}.epub"), EPUB_TYPE, "EPUB")


def _xml_response(root: ET.Element, kind: str) -> Response:
    media = NAV_TYPE if kind == "navigation" else ACQ_TYPE
    return Response(content=ET.tostring(root, encoding="utf-8", xml_declaration=True), media_type=media)


def _novels_with_epub(db: Session, novel_ids: list[int]) -> set[int]:
    if not novel_ids:
        return set()
    rows = (
        db.query(Chapter.novel_id)
        .filter(
            Chapter.novel_id.in_(novel_ids),
            Chapter.content_status == ContentStatus.PRESENT,
            Chapter.content.isnot(None),
        )
        .distinct()
        .all()
    )
    return {row[0] for row in rows}


def _user_novel_query(db: Session, user: User):
    return (
        db.query(Novel)
        .join(Library, Library.id == Novel.library_id)
        .filter(Library.user_id == user.id)
    )


def _acquisition_page(
    request: Request,
    db: Session,
    user: User,
    *,
    query,
    feed_id: str,
    title: str,
    page: int,
) -> Response:
    novels = query.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE + 1).all()
    has_next = len(novels) > PAGE_SIZE
    novels = novels[:PAGE_SIZE]
    feed = _feed(request, feed_id=feed_id, title=title, kind="acquisition")
    if page > 1:
        _link(feed, "previous", _href(request, request.url.path, {**dict(request.query_params), "page": page - 1}), ACQ_TYPE)
    if has_next:
        _link(feed, "next", _href(request, request.url.path, {**dict(request.query_params), "page": page + 1}), ACQ_TYPE)
    _novel_entries(feed, request, novels, _novels_with_epub(db, [novel.id for novel in novels]))
    return _xml_response(feed, "acquisition")


# ---- feeds --------------------------------------------------------------

@router.get("")
@router.get("/")
def root_feed(request: Request, db: Session = Depends(get_db), user: User = Depends(get_opds_user)):
    feed = _feed(request, feed_id="urn:nexus:opds:root", title="Nexus", kind="navigation")
    _nav_entry(feed, request, entry_id="urn:nexus:opds:following", title="Following",
               target="/opds/following", summary="Stories you follow")
    _nav_entry(feed, request, entry_id="urn:nexus:opds:recent", title="Recently updated",
               target="/opds/recent", summary="Stories ordered by their latest update")
    libraries = db.query(Library).filter(Library.user_id == user.id).order_by(Library.name.asc()).all()
    for library in libraries:
        _nav_entry(feed, request, entry_id=f"urn:nexus:library:{library.id}", title=library.name,
                   target=f"/opds/libraries/{library.id}", summary=f"Library: {library.name}")
    return _xml_response(feed, "navigation")


@router.get("/following")
def following_feed(
    request: Request,
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_opds_user),
):
    query = (
        _user_novel_query(db, user)
        .join(UserNovelFollow, UserNovelFollow.novel_id == Novel.id)
        .filter(UserNovelFollow.user_id == user.id)
        .order_by(Novel.title.asc(), Novel.id.asc())
    )
    return _acquisition_page(request, db, user, query=query, feed_id="urn:nexus:opds:following", title="Following", page=page)


@router.get("/recent")
def recent_feed(
    request: Request,
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_opds_user),
):
    query = _user_novel_query(db, user).order_by(Novel.updated_date.desc().nullslast(), Novel.id.desc())
    return _acquisition_page(request, db, user, query=query, feed_id="urn:nexus:opds:recent", title="Recently updated", page=page)


@router.get("/libraries/{library_id:int}")
def library_feed(
    library_id: int,
    request: Request,
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_opds_user),
):
    library = db.query(Library).filter(Library.id == library_id, Library.user_id == user.id).first()
    if library is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Library not found")
    query = _user_novel_query(db, user).filter(Novel.library_id == library.id).order_by(Novel.title.asc(), Novel.id.asc())
    return _acquisition_page(request, db, user, query=query, feed_id=f"urn:nexus:library:{library.id}", title=library.name, page=page)


@router.get("/search")
def search_feed(
    request: Request,
    q: str = Query(default="", max_length=200),
    page: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(get_opds_user),
):
    term = q.strip()
    if not term:
        return _acquisition_page(request, db, user, query=_user_novel_query(db, user).filter(false()),
                                 feed_id="urn:nexus:opds:search", title="Search", page=1)
    pattern = f"%{term}%"
    query = (
        _user_novel_query(db, user)
        .filter(or_(Novel.title.ilike(pattern), Novel.author.ilike(pattern)))
        .order_by(Novel.title.asc(), Novel.id.asc())
    )
    return _acquisition_page(request, db, user, query=query, feed_id="urn:nexus:opds:search",
                             title=f"Search: {term}", page=page)


@router.get("/opensearch.xml")
def opensearch_description(request: Request):
    root = ET.Element(f"{{{OPENSEARCH_NS}}}OpenSearchDescription")
    ET.SubElement(root, f"{{{OPENSEARCH_NS}}}ShortName").text = "Nexus"
    ET.SubElement(root, f"{{{OPENSEARCH_NS}}}Description").text = "Search your Nexus libraries"
    ET.SubElement(root, f"{{{OPENSEARCH_NS}}}InputEncoding").text = "UTF-8"
    ET.SubElement(root, f"{{{OPENSEARCH_NS}}}OutputEncoding").text = "UTF-8"
    ET.SubElement(root, f"{{{ATOM_NS}}}link", {
        "rel": "search",
        "type": ACQ_TYPE,
        "href": _href(request, "/opds/search") + "?q={searchTerms}",
    })
    ET.SubElement(root, f"{{{OPENSEARCH_NS}}}Url", {
        "type": ACQ_TYPE,
        "template": _href(request, "/opds/search") + "?q={searchTerms}",
    })
    return Response(content=ET.tostring(root, encoding="utf-8", xml_declaration=True), media_type=SEARCH_TYPE)


# ---- EPUB download -----------------------------------------------------

def _http_date(value: datetime) -> str:
    return format_datetime(value.replace(tzinfo=UTC) if value.tzinfo is None else value, usegmt=True)


@router.get("/novels/{novel_id:int}.epub")
def download_novel_epub(
    novel_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_opds_user),
):
    novel = _user_novel_query(db, user).filter(Novel.id == novel_id).first()
    if novel is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Novel not found")
    try:
        built = epub_service.ensure_build(db, novel)
    except epub_service.NoDownloadedChapters:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Download at least one chapter first")

    etag = f'"{built.build.fingerprint[:32]}"'
    modified = built.build.updated_at or built.build.created_at or datetime.now(UTC)
    if modified.tzinfo is None:
        modified = modified.replace(tzinfo=UTC)
    headers = {"ETag": etag, "Last-Modified": _http_date(modified), "Cache-Control": "private, no-cache"}

    if_none_match = request.headers.get("if-none-match")
    if if_none_match is not None:
        if etag in [candidate.strip() for candidate in if_none_match.split(",")] or if_none_match.strip() == "*":
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    elif request.headers.get("if-modified-since"):
        try:
            since = parsedate_to_datetime(request.headers["if-modified-since"])
        except (TypeError, ValueError):
            since = None
        if since is not None and since.tzinfo is not None and modified.replace(microsecond=0) <= since:
            return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    filename = f"{(novel.title or 'nexus-novel').replace(' ', '-').lower()}.epub"
    return FileResponse(built.path, media_type=EPUB_TYPE, filename=filename, headers=headers)
