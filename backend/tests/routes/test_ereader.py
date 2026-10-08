import base64
import hashlib
import zipfile
from datetime import datetime
from io import BytesIO
from urllib.parse import urljoin
from xml.etree import ElementTree as ET

import pytest

from app.auth.passwords import hash_password
from app.models.chapter import Chapter, ContentStatus
from app.models.ereader import EpubBuild, KosyncProgress
from app.models.follow import UserNovelFollow
from app.models.library import Library
from app.models.novel import Novel
from app.models.reading_progress import ReadingProgress
from app.services.epub_service import partial_md5
from config.settings import settings

ATOM = "{http://www.w3.org/2005/Atom}"
ACQUISITION = "application/atom+xml;profile=opds-catalog;kind=acquisition"
NAVIGATION = "application/atom+xml;profile=opds-catalog;kind=navigation"
ACCOUNT_PASSWORD = "account-pass-123"


@pytest.fixture(autouse=True)
def download_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DOWNLOAD_PATH", str(tmp_path))
    return tmp_path


@pytest.fixture
def reader(db, test_user):
    test_user.password = hash_password(ACCOUNT_PASSWORD)
    db.commit()
    return test_user


def basic(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def make_app_password(client, auth_headers, scope: str) -> str:
    response = client.post("/app-passwords", json={"label": "Kindle", "scope": scope}, headers=auth_headers)
    assert response.status_code == 201
    return response.json()["secret"]


def add_novel(db, library: Library, title: str, chapters: int = 2) -> Novel:
    novel = Novel(
        title=title,
        author="Author A",
        library_id=library.id,
        description="<p>A <b>great</b> story about &amp; things.</p>",
        updated_date=datetime(2026, 1, 1),
    )
    db.add(novel)
    db.flush()
    for number in range(1, chapters + 1):
        db.add(
            Chapter(
                novel_id=novel.id,
                chapter_number=number,
                title=f"Chapter {number}",
                content=f"Paragraph {number}.\nSecond line of {number}.",
                content_status=ContentStatus.PRESENT,
            )
        )
    db.commit()
    return novel


def parse(response) -> ET.Element:
    assert response.status_code == 200, response.text
    return ET.fromstring(response.content)


@pytest.fixture
def library(db, reader):
    library = Library(name="Shelf", user_id=reader.id)
    db.add(library)
    db.commit()
    return library


# ---- app passwords -------------------------------------------------------

def test_app_password_is_returned_once_and_never_listed(client, auth_headers):
    created = client.post("/app-passwords", json={"label": "Kobo", "scope": "opds"}, headers=auth_headers)
    assert created.status_code == 201
    body = created.json()
    assert len(body["secret"]) >= 20

    listed = client.get("/app-passwords", headers=auth_headers).json()
    assert [item["label"] for item in listed] == ["Kobo"]
    assert "secret" not in listed[0]
    assert body["secret"] not in client.get("/app-passwords", headers=auth_headers).text


def test_app_password_rejects_unknown_scope(client, auth_headers):
    response = client.post("/app-passwords", json={"label": "x", "scope": "admin"}, headers=auth_headers)
    assert response.status_code == 422


def test_app_passwords_need_a_web_session(client):
    assert client.get("/app-passwords").status_code == 401


# ---- OPDS authentication ---------------------------------------------------

def test_opds_requires_basic_auth_with_a_challenge(client):
    response = client.get("/opds/")
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")


def test_account_password_is_not_accepted_for_opds(client, reader):
    assert client.get("/opds/", headers=basic(reader.username, ACCOUNT_PASSWORD)).status_code == 401


def test_opds_app_password_works_and_kosync_scope_does_not(client, auth_headers, reader):
    opds_secret = make_app_password(client, auth_headers, "opds")
    kosync_secret = make_app_password(client, auth_headers, "kosync")

    ok = client.get("/opds/", headers=basic(reader.username, opds_secret))
    assert ok.status_code == 200
    assert ok.headers["content-type"] == NAVIGATION
    assert client.get("/opds/", headers=basic(reader.username, kosync_secret)).status_code == 401


def test_revoked_app_password_fails_and_revoke_is_idempotent(client, auth_headers, reader):
    secret = make_app_password(client, auth_headers, "opds")
    app_password_id = client.get("/app-passwords", headers=auth_headers).json()[0]["id"]

    assert client.delete(f"/app-passwords/{app_password_id}", headers=auth_headers).status_code == 204
    assert client.get("/opds/", headers=basic(reader.username, secret)).status_code == 401
    assert client.delete(f"/app-passwords/{app_password_id}", headers=auth_headers).status_code == 204
    assert client.delete("/app-passwords/999999", headers=auth_headers).status_code == 404


# ---- OPDS feeds ------------------------------------------------------------

def test_root_feed_is_navigation_atom_with_required_elements(client, auth_headers, reader, library):
    secret = make_app_password(client, auth_headers, "opds")
    root = parse(client.get("/opds/", headers=basic(reader.username, secret)))

    assert root.tag == f"{ATOM}feed"
    for tag in ("id", "title", "updated"):
        assert root.find(f"{ATOM}{tag}") is not None
    titles = [entry.find(f"{ATOM}title").text for entry in root.findall(f"{ATOM}entry")]
    assert titles == ["Following", "Recently updated", "Shelf"]
    for entry in root.findall(f"{ATOM}entry"):
        link = entry.find(f"{ATOM}link[@rel='subsection']")
        assert link is not None and link.get("type") == ACQUISITION
        assert entry.find(f"{ATOM}updated") is not None


def test_library_feed_links_epub_relative_to_the_feed(client, auth_headers, reader, library, db):
    secret = make_app_password(client, auth_headers, "opds")
    novel = add_novel(db, library, "Mother of Learning")
    response = client.get(f"/opds/libraries/{library.id}", headers=basic(reader.username, secret))
    feed = parse(response)
    assert response.headers["content-type"] == ACQUISITION

    entry = feed.find(f"{ATOM}entry")
    assert entry.find(f"{ATOM}title").text == "Mother of Learning"
    assert entry.find(f"{ATOM}author/{ATOM}name").text == "Author A"
    assert "great story about & things" in entry.find(f"{ATOM}summary").text
    assert "<b>" not in entry.find(f"{ATOM}summary").text
    acquisition = entry.find(f"{ATOM}link[@rel='http://opds-spec.org/acquisition']")
    assert acquisition.get("type") == "application/epub+zip"
    # Relative references resolve against the feed URL, so a /api prefix survives.
    feed_url = f"http://reader.test/api/opds/libraries/{library.id}"
    assert urljoin(feed_url, acquisition.get("href")) == f"http://reader.test/api/opds/novels/{novel.id}.epub"


def test_novel_without_downloaded_chapters_has_no_acquisition_link(client, auth_headers, reader, library, db):
    secret = make_app_password(client, auth_headers, "opds")
    novel = Novel(title="Not downloaded", library_id=library.id)
    db.add(novel)
    db.commit()
    feed = parse(client.get(f"/opds/libraries/{library.id}", headers=basic(reader.username, secret)))
    assert feed.find(f"{ATOM}entry/{ATOM}link[@rel='http://opds-spec.org/acquisition']") is None


def test_library_feed_paginates_with_next_and_previous(client, auth_headers, reader, library, db):
    secret = make_app_password(client, auth_headers, "opds")
    for index in range(26):
        add_novel(db, library, f"Story {index:02d}", chapters=1)
    headers = basic(reader.username, secret)

    first = parse(client.get(f"/opds/libraries/{library.id}", headers=headers))
    assert len(first.findall(f"{ATOM}entry")) == 25
    next_href = first.find(f"{ATOM}link[@rel='next']").get("href")
    assert first.find(f"{ATOM}link[@rel='previous']") is None

    second = parse(client.get(f"/opds/libraries/{library.id}", params={"page": 2}, headers=headers))
    assert len(second.findall(f"{ATOM}entry")) == 1
    assert second.find(f"{ATOM}link[@rel='next']") is None
    assert second.find(f"{ATOM}link[@rel='previous']") is not None
    assert next_href.endswith("page=2")


def test_search_only_covers_own_libraries(client, auth_headers, reader, library, db):
    secret = make_app_password(client, auth_headers, "opds")
    add_novel(db, library, "Needle in a library")
    other = Library(name="Other", user_id=reader.id + 1000)
    db.add(other)
    db.flush()
    add_novel(db, other, "Needle elsewhere")

    feed = parse(client.get("/opds/search", params={"q": "needle"}, headers=basic(reader.username, secret)))
    titles = [entry.find(f"{ATOM}title").text for entry in feed.findall(f"{ATOM}entry")]
    assert titles == ["Needle in a library"]


def test_opensearch_description_points_at_search(client, auth_headers, reader):
    secret = make_app_password(client, auth_headers, "opds")
    response = client.get("/opds/opensearch.xml", headers=basic(reader.username, secret))
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/opensearchdescription+xml")
    assert "search?q={searchTerms}" in response.text


def test_following_feed_lists_only_followed_novels(client, auth_headers, reader, library, db):
    secret = make_app_password(client, auth_headers, "opds")
    followed = add_novel(db, library, "Followed one")
    add_novel(db, library, "Not followed")
    db.add(UserNovelFollow(user_id=reader.id, novel_id=followed.id))
    db.commit()
    feed = parse(client.get("/opds/following", headers=basic(reader.username, secret)))
    titles = [entry.find(f"{ATOM}title").text for entry in feed.findall(f"{ATOM}entry")]
    assert titles == ["Followed one"]


# ---- EPUB download and cache ---------------------------------------------

def test_epub_download_is_a_valid_zip_and_honours_etags(client, auth_headers, reader, library, db):
    secret = make_app_password(client, auth_headers, "opds")
    novel = add_novel(db, library, "Mother of Learning", chapters=3)
    headers = basic(reader.username, secret)

    response = client.get(f"/opds/novels/{novel.id}.epub", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/epub+zip"
    archive = zipfile.ZipFile(BytesIO(response.content))
    assert archive.namelist()[0] == "mimetype"
    assert archive.read("mimetype") == b"application/epub+zip"
    assert {"OEBPS/chapter-1.xhtml", "OEBPS/chapter-3.xhtml", "OEBPS/content.opf"} <= set(archive.namelist())

    etag = response.headers["etag"]
    assert response.headers.get("last-modified")
    cached = client.get(f"/opds/novels/{novel.id}.epub", headers={**headers, "If-None-Match": etag})
    assert cached.status_code == 304


def test_epub_cache_rebuilds_when_a_chapter_is_added(client, auth_headers, reader, library, db, download_dir):
    secret = make_app_password(client, auth_headers, "opds")
    novel = add_novel(db, library, "Growing", chapters=2)
    headers = basic(reader.username, secret)

    first = client.get(f"/opds/novels/{novel.id}.epub", headers=headers)
    db.add(
        Chapter(
            novel_id=novel.id,
            chapter_number=3,
            title="Chapter 3",
            content="New material.",
            content_status=ContentStatus.PRESENT,
        )
    )
    db.commit()
    second = client.get(f"/opds/novels/{novel.id}.epub", headers=headers)

    assert first.content != second.content
    assert first.headers["etag"] != second.headers["etag"]
    assert "OEBPS/chapter-3.xhtml" in zipfile.ZipFile(BytesIO(second.content)).namelist()
    assert db.query(EpubBuild).filter(EpubBuild.novel_id == novel.id).count() == 2
    # Only the current file stays on disk.
    assert len(list((download_dir / "epub").glob(f"{novel.id}-*.epub"))) == 1


def test_partial_md5_samples_follow_koreader_offsets():
    data = bytes(range(256)) * 200  # 51200 bytes
    expected = hashlib.md5()
    for offset in (256, 1024, 4096, 16384):
        expected.update(data[offset : offset + 1024])
    assert partial_md5(data) == expected.hexdigest()


# ---- kosync ----------------------------------------------------------------

def _kosync_key(secret: str) -> str:
    return hashlib.md5(secret.encode("utf-8")).hexdigest()


def test_kosync_round_trip_updates_reading_progress(client, auth_headers, reader, library, db):
    opds_secret = make_app_password(client, auth_headers, "opds")
    kosync_secret = make_app_password(client, auth_headers, "kosync")
    novel = add_novel(db, library, "Mother of Learning", chapters=3)

    epub = client.get(f"/opds/novels/{novel.id}.epub", headers=basic(reader.username, opds_secret)).content
    document = partial_md5(epub)
    sync_headers = {"x-auth-user": reader.username, "x-auth-key": _kosync_key(kosync_secret)}

    assert client.get("/kosync/users/auth", headers=sync_headers).json() == {"authorized": "OK"}
    assert client.get("/kosync/users/auth", headers={"x-auth-user": reader.username, "x-auth-key": _kosync_key("nope")}).status_code == 401
    assert client.get("/kosync/users/auth", headers={"x-auth-user": reader.username, "x-auth-key": ACCOUNT_PASSWORD}).status_code == 401

    put = client.put(
        "/kosync/syncs/progress",
        json={
            "document": document,
            "progress": "/body/DocFragment[2]/body/p[1]/text().0",
            "percentage": 0.4,
            "device": "KOReader",
            "device_id": "kobo-1",
        },
        headers=sync_headers,
    )
    assert put.status_code == 200
    assert put.json()["document"] == document

    got = client.get(f"/kosync/syncs/progress/{document}", headers=sync_headers).json()
    assert got["progress"] == "/body/DocFragment[2]/body/p[1]/text().0"
    assert got["percentage"] == pytest.approx(0.4)
    assert got["device"] == "KOReader"

    progress = db.query(ReadingProgress).filter(ReadingProgress.novel_id == novel.id, ReadingProgress.user_id == reader.id).one()
    assert progress.chapter_number == 2
    assert progress.percent == pytest.approx(40)
    assert db.query(KosyncProgress).filter(KosyncProgress.user_id == reader.id).count() == 1


def test_kosync_unknown_document_and_registration(client, auth_headers, reader):
    kosync_secret = make_app_password(client, auth_headers, "kosync")
    sync_headers = {"x-auth-user": reader.username, "x-auth-key": _kosync_key(kosync_secret)}
    unknown = "0" * 32
    assert client.get(f"/kosync/syncs/progress/{unknown}", headers=sync_headers).json() == {}
    put = client.put(
        "/kosync/syncs/progress",
        json={"document": unknown, "progress": "", "percentage": 0.1},
        headers=sync_headers,
    )
    assert put.status_code == 404
    assert client.post("/kosync/users/create", json={"username": "x", "password": "y"}).status_code == 402
