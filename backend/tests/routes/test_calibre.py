"""Calibre interop: metadata.db import jobs, FanFicFare URL lists, Calibre export."""

import asyncio
import base64
import io
import sqlite3
import zipfile
from types import SimpleNamespace

from app.models.follow import UserNovelFollow
from app.models.novel import Novel
from app.models.novel_personal import NovelPersonalData, NovelUserTag
from app.services import calibre_service
from app.services import import_job_service as imports
from app.services.epub_service import render_epub
from tests.routes.conftest import TestingSessionLocal
from tests.routes.test_imports import FakeScrape, _metadata_scrape


def _metadata_db(path, *, with_books=True) -> bytes:
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT, author_sort TEXT, path TEXT);
        CREATE TABLE identifiers (id INTEGER PRIMARY KEY, book INTEGER, type TEXT, val TEXT);
        CREATE TABLE comments (id INTEGER PRIMARY KEY, book INTEGER, text TEXT);
        CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE books_tags_link (id INTEGER PRIMARY KEY, book INTEGER, tag INTEGER);
        CREATE TABLE ratings (id INTEGER PRIMARY KEY, rating INTEGER);
        CREATE TABLE books_ratings_link (id INTEGER PRIMARY KEY, book INTEGER, rating INTEGER);
        CREATE TABLE custom_columns (id INTEGER PRIMARY KEY, label TEXT, name TEXT, datatype TEXT);
        CREATE TABLE custom_column_1 (id INTEGER PRIMARY KEY, book INTEGER, value BOOL);
        CREATE TABLE custom_column_2 (id INTEGER PRIMARY KEY, book INTEGER, value TEXT);
    """)
    conn.executemany("INSERT INTO books VALUES (?,?,?,?)", [
        (1, "Alpha", "A", "a"), (2, "Beta", "B", "b"), (3, "Gamma", "G", "g"), (4, "Delta", "D", "d")])
    conn.executemany("INSERT INTO identifiers (book, type, val) VALUES (?,?,?)", [
        (1, "ffnet", "111"), (2, "ao3", "222")])
    conn.execute("INSERT INTO comments (book, text) VALUES (3, 'Source: https://www.royalroad.com/fiction/333/gamma')")
    conn.executemany("INSERT INTO tags (id, name) VALUES (?,?)", [(1, "Fantasy"), (2, "Slow burn")])
    conn.executemany("INSERT INTO books_tags_link (book, tag) VALUES (?,?)", [(1, 1), (1, 2)])
    conn.execute("INSERT INTO ratings (id, rating) VALUES (1, 8)")
    conn.execute("INSERT INTO books_ratings_link (book, rating) VALUES (1, 1)")
    conn.execute("INSERT INTO custom_columns VALUES (1, 'read', 'read', 'bool')")
    conn.execute("INSERT INTO custom_columns VALUES (2, 'fanfic_url', 'fanfic_url', 'text')")
    conn.executemany("INSERT INTO custom_column_1 (book, value) VALUES (?,?)", [(1, 1), (2, 0)])
    conn.commit()
    conn.close()
    with open(path, "rb") as handle:
        return handle.read()


def test_calibre_library_books_map_to_urls_tags_rating_and_read(tmp_path):
    data = _metadata_db(tmp_path / "metadata.db")
    books = {book.title: book for book in calibre_service.read_calibre_library(data)}
    assert books["Alpha"].url == "https://www.fanfiction.net/s/111"
    assert books["Alpha"].tags == ["Fantasy", "Slow burn"]
    assert books["Alpha"].rating == 4 and books["Alpha"].read is True
    assert books["Beta"].url == "https://archiveofourown.org/works/222" and books["Beta"].read is False
    assert books["Gamma"].url == "https://www.royalroad.com/fiction/333/gamma"
    assert books["Delta"].url is None
    assert calibre_service.stars_from_calibre(0) is None and calibre_service.stars_from_calibre(9) == 5


def test_calibre_upload_rejects_non_calibre_files(client, test_library, auth_headers, tmp_path):
    not_sqlite = base64.b64encode(b"plain text").decode()
    assert client.post("/imports/calibre", json={"library_id": test_library.id, "data_base64": not_sqlite},
                       headers=auth_headers).status_code == 422
    path = tmp_path / "other.db"
    sqlite3.connect(path).executescript("CREATE TABLE other (x INTEGER);")
    other = base64.b64encode(path.read_bytes()).decode()
    response = client.post("/imports/calibre", json={"library_id": test_library.id, "data_base64": other}, headers=auth_headers)
    assert response.status_code == 422 and "metadata.db" in response.json()["detail"]


def test_calibre_import_job_links_novels_with_personal_data(client, db, test_user, test_library, auth_headers, monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.metadata_client.scrape_novel_by_url", _metadata_scrape())
    data = base64.b64encode(_metadata_db(tmp_path / "metadata.db")).decode()
    job = client.post("/imports/calibre", json={"library_id": test_library.id, "data_base64": data}, headers=auth_headers).json()
    asyncio.run(imports.run_import_job(job["id"], TestingSessionLocal, scrape=FakeScrape()))
    items = {item["label"]: item for item in client.get(f"/imports/{job['id']}", headers=auth_headers).json()["items"]}
    assert items["Alpha"]["status"] == "linked" and items["Gamma"]["status"] == "linked"
    assert items["Delta"]["status"] == "unsupported"

    alpha = db.query(Novel).filter(Novel.url == "https://www.fanfiction.net/s/111").one()
    personal = db.query(NovelPersonalData).filter(NovelPersonalData.novel_id == alpha.id).one()
    assert personal.rating == 4
    assert sorted(tag.tag for tag in db.query(NovelUserTag).filter(NovelUserTag.novel_id == alpha.id)) == ["fantasy", "slow burn"]
    assert db.query(UserNovelFollow).filter(UserNovelFollow.novel_id == alpha.id).one().state == "completed"
    beta = db.query(Novel).filter(Novel.url == "https://archiveofourown.org/works/222").one()
    assert db.query(UserNovelFollow).filter(UserNovelFollow.novel_id == beta.id).one().state == "plan_to_read"


def test_fanficfare_csv_export_lists_urls(tmp_path):
    csv = 'url,title,author\n"https://www.fanfiction.net/s/1/1/","One, two","Writer"\nhttps://archiveofourown.org/works/2,Two,Me\n'
    assert imports.extract_urls(csv) == ["https://www.fanfiction.net/s/1/1/", "https://archiveofourown.org/works/2"]


def test_calibre_export_opf_carries_source_tags_and_rating():
    novel = SimpleNamespace(id=5, title="Epic & Long", author="Ann", url="https://www.fanfiction.net/s/9/1/")
    chapter = SimpleNamespace(title="One", content="Text", chapter_number=1)
    epub = render_epub(novel, [chapter])
    rewritten = calibre_service._with_calibre_metadata(epub, novel, ["Fantasy", "A&B"], 4)
    with zipfile.ZipFile(io.BytesIO(rewritten)) as archive:
        assert archive.namelist()[0] == "mimetype"
        opf = archive.read("OEBPS/content.opf").decode()
    assert "<dc:title>Epic &amp; Long</dc:title>" in opf and "<dc:creator>Ann</dc:creator>" in opf
    assert "<dc:source>https://www.fanfiction.net/s/9/1/</dc:source>" in opf
    assert "<dc:subject>Fantasy</dc:subject>" in opf and "<dc:subject>A&amp;B</dc:subject>" in opf
    assert '<meta name="calibre:rating" content="8"/>' in opf


def test_calibre_export_endpoint_streams_zip(client, auth_headers):
    response = client.get("/me/export/calibre", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert zipfile.ZipFile(io.BytesIO(response.content)).namelist() == []


def test_crafted_calibre_file_cannot_spin_the_server(tmp_path, monkeypatch):
    path = tmp_path / "metadata.db"
    _metadata_db(path)
    conn = sqlite3.connect(path)
    # A "custom column" that is an endless recursive view is skipped, not run.
    conn.executescript("""
        DROP TABLE custom_column_2;
        CREATE VIEW custom_column_2 AS WITH RECURSIVE n(book, value) AS
            (SELECT 1, 'x' UNION ALL SELECT book + 1, value FROM n) SELECT book, value FROM n;
    """)
    conn.close()
    data = path.read_bytes()
    assert len(calibre_service.read_calibre_library(data)) == 4
    # Any other runaway query is cut off by the work budget.
    monkeypatch.setattr(calibre_service, "SQLITE_PROGRESS_INTERVAL", 1)
    monkeypatch.setattr(calibre_service, "MAX_SQLITE_PROGRESS_CALLS", 0)
    try:
        calibre_service.read_calibre_library(data)
    except calibre_service.CalibreFormatError:
        pass
    else:
        raise AssertionError("the work budget did not stop the read")


def test_epub_members_that_inflate_too_far_are_not_read():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("META-INF/container.xml", b"<a>" + b" " * (imports.EPUB_MEMBER_MAX_BYTES + 1) + b"</a>")
        archive.writestr("title.xhtml", b"https://www.royalroad.com/fiction/1/x " + b" " * (imports.EPUB_MEMBER_MAX_BYTES + 1))
        archive.writestr("content.opf", b"<package/>")
    assert len(buffer.getvalue()) < 100_000
    assert imports.epub_source_url(buffer.getvalue()) is None
