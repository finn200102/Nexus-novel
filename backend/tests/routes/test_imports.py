"""Durable import jobs: sources, per-item report, worker processing."""

import asyncio
import base64
import io
import zipfile
from unittest.mock import AsyncMock

import pytest

from app.models.import_job import ImportJob
from app.models.novel import Novel
from app.services import import_job_service as imports
from tests.routes.conftest import TestingSessionLocal

FFN = "https://www.fanfiction.net/s/{}/1/"
RR = "https://www.royalroad.com/fiction/{}/story-{}"
AO3 = "https://archiveofourown.org/works/{}"


def _epub(opf_meta: str = "", title_page: str = "") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        archive.writestr(
            "OEBPS/content.opf",
            '<package xmlns="http://www.idpf.org/2007/opf"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f"<dc:title>T</dc:title>{opf_meta}</metadata></package>",
        )
        archive.writestr("OEBPS/title_page.xhtml", f"<html><body>{title_page}</body></html>")
    return buffer.getvalue()


def test_extract_urls_from_text_csv_and_royal_road_paths():
    text = f'title,url\n"A",{FFN.format(1)}\nB, {AO3.format(2)}.\n'
    assert imports.extract_urls(text) == [FFN.format(1), AO3.format(2)]
    pasted = "Follows\n/fiction/12/one\nroyalroad.com/fiction/34/two\nhttps://www.royalroad.com/fiction/12/one"
    urls = imports.extract_urls(pasted, royalroad_paths=True)
    assert urls == ["https://www.royalroad.com/fiction/12/one", "https://www.royalroad.com/fiction/34"]


def test_epub_source_url_from_fanficfare_fichub_and_title_page():
    assert imports.epub_source_url(_epub(f"<dc:source>{FFN.format(5)}</dc:source>")) == FFN.format(5)
    assert imports.epub_source_url(_epub(f"<dc:identifier>url:{AO3.format(6)}</dc:identifier>")) == AO3.format(6)
    page = f'<a href="https://fichub.net/x">FicHub</a> Source: <a href="{RR.format(7, 7)}">link</a>'
    assert imports.epub_source_url(_epub("<dc:identifier>urn:uuid:1</dc:identifier>", page)) == RR.format(7, 7)
    assert imports.epub_source_url(b"not a zip") is None


class FakeScrape:
    """Stands in for the add-novel scrape wait: marks the novel done or failed."""

    def __init__(self, failing_metadata_ids=()):
        self.failing = set(failing_metadata_ids)
        self.calls = []

    def __call__(self, novel_id, metadata_id, session_factory, loop):
        self.calls.append(metadata_id)
        db = session_factory()
        try:
            novel = db.get(Novel, novel_id)
            if metadata_id in self.failing:
                novel.scrape_status, novel.scrape_error = "failed", "source returned 404"
            else:
                novel.scrape_status, novel.title = "completed", f"Scraped {metadata_id}"
            db.commit()
        finally:
            db.close()


def _metadata_scrape(refuse_urls=()):
    counter = {"next": 1000}

    async def scrape_by_url(url, site):
        if url in refuse_urls:
            return {"success": False, "novel_id": None, "message": "Unknown site"}
        counter["next"] += 1
        return {"success": True, "novel_id": counter["next"], "message": "scraping started"}

    return AsyncMock(side_effect=scrape_by_url)


def test_two_hundred_mixed_urls_report_every_item(client, db, test_user, test_library, auth_headers, monkeypatch):
    existing = Novel(title="Already here", url=RR.format(1, 1), library_id=test_library.id, scrape_status="completed")
    db.add(existing)
    db.commit()

    lines = []
    for n in range(1, 61):
        lines.append(RR.format(n, n))  # 1 is already in the library
    for n in range(1, 51):
        lines.append(FFN.format(n))
    for n in range(1, 41):
        lines.append(AO3.format(n))
    for n in range(1, 21):
        lines.append(f"https://:443/story/{n}")  # unsupported: no host
    for n in range(1, 21):
        lines.append(FFN.format(n))  # listed twice
    for n in range(1, 11):
        lines.append(f"https://www.webnovel.com/book/{n}")  # metadata server refuses some
    assert len(lines) == 200

    refused = {f"https://www.webnovel.com/book/{n}" for n in range(1, 6)}
    metadata_scrape = _metadata_scrape(refused)
    monkeypatch.setattr("app.services.metadata_client.scrape_novel_by_url", metadata_scrape)

    response = client.post(
        "/imports/urls", json={"library_id": test_library.id, "text": "\n".join(lines)}, headers=auth_headers
    )
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    assert response.json()["total_items"] == 200

    # Metadata ids are handed out in order; make two of the stories fail their scrape.
    fake = FakeScrape(failing_metadata_ids={1060, 1061})
    asyncio.run(imports.run_import_job(job_id, TestingSessionLocal, scrape=fake))

    report = client.get(f"/imports/{job_id}", headers=auth_headers).json()
    assert report["status"] == "finished"
    assert len(report["items"]) == 200
    assert all(item["status"] in imports.FINAL_ITEM_STATUSES for item in report["items"])
    assert report["counts"] == {"linked": 152, "duplicate": 21, "unsupported": 20, "failed": 7}
    failed = [item for item in report["items"] if item["status"] == "failed"]
    assert all(item["reason"] for item in failed)
    assert {item["reason"] for item in failed} == {"Unknown site", "source returned 404"}
    duplicate_reasons = {item["reason"] for item in report["items"] if item["status"] == "duplicate"}
    assert duplicate_reasons == {"already in this library", "listed more than once in this import"}
    # One metadata request per new story, made one at a time by the worker.
    assert metadata_scrape.await_count == 159
    assert db.query(Novel).filter(Novel.library_id == test_library.id).count() == 1 + 154


def test_ao3_bookmarks_are_expanded_page_by_page(client, db, test_library, auth_headers, monkeypatch):
    pages = {
        1: [{"url": AO3.format(1), "title": "One"}, {"url": AO3.format(2), "title": "Two"}],
        2: [{"url": AO3.format(3), "title": "Three"}],
        3: [],
    }
    calls = []

    async def live_listing(kind, params):
        calls.append((kind, params["site"], params["list"], params["user"], params["page"]))
        return {"site": params["site"], "page": params["page"], "results": pages[params["page"]], "error": None}

    monkeypatch.setattr("app.services.metadata_client.live_listing", live_listing)
    monkeypatch.setattr("app.services.metadata_client.scrape_novel_by_url", _metadata_scrape())
    job = client.post(
        "/imports/list", json={"library_id": test_library.id, "source": "ao3_bookmarks", "user": "reader"}, headers=auth_headers
    ).json()
    assert job["status"] == "expanding"

    asyncio.run(imports.run_import_job(job["id"], TestingSessionLocal, scrape=FakeScrape()))

    assert [call[-1] for call in calls] == [1, 2, 3]
    assert calls[0][:4] == ("user-list", "archive", "bookmarks", "reader")
    report = client.get(f"/imports/{job['id']}", headers=auth_headers).json()
    assert report["status"] == "finished"
    assert [(item["url"], item["status"]) for item in report["items"]] == [
        (AO3.format(1), "linked"), (AO3.format(2), "linked"), (AO3.format(3), "linked"),
    ]


def test_list_import_reports_a_private_or_missing_list(client, test_library, auth_headers, monkeypatch):
    async def live_listing(kind, params):
        return {"results": [], "error": {"code": "source_blocked", "message": "HTTP 403"}}

    monkeypatch.setattr("app.services.metadata_client.live_listing", live_listing)
    job = client.post(
        "/imports/list", json={"library_id": test_library.id, "source": "ffn_favorites", "user": "123"}, headers=auth_headers
    ).json()
    asyncio.run(imports.run_import_job(job["id"], TestingSessionLocal, scrape=FakeScrape()))
    report = client.get(f"/imports/{job['id']}", headers=auth_headers).json()
    assert report["status"] == "failed"
    assert report["error"].startswith("source_blocked")
    bad = client.post("/imports/list", json={"library_id": test_library.id, "source": "ffn_favorites", "user": "name"}, headers=auth_headers)
    assert bad.status_code == 422


def test_epub_import_and_me_import_jobs_are_processed(client, db, test_user, test_library, auth_headers, monkeypatch):
    monkeypatch.setattr("app.services.metadata_client.scrape_novel_by_url", _metadata_scrape())
    files = [
        {"name": "good.epub", "data_base64": base64.b64encode(_epub(f"<dc:source>{FFN.format(9)}</dc:source>")).decode()},
        {"name": "plain.epub", "data_base64": base64.b64encode(_epub()).decode()},
    ]
    job = client.post("/imports/epub", json={"library_id": test_library.id, "files": files}, headers=auth_headers).json()
    asyncio.run(imports.run_import_job(job["id"], TestingSessionLocal, scrape=FakeScrape()))
    items = client.get(f"/imports/{job['id']}", headers=auth_headers).json()["items"]
    assert [(item["label"], item["status"]) for item in items] == [("good.epub", "linked"), ("plain.epub", "unsupported")]

    document = {
        "format": "nexus-user-export",
        "version": 1,
        "libraries": [{"name": "Restored", "novels": [{"url": RR.format(77, 77), "title": "Restored story"}]}],
    }
    imported = client.post("/me/import", json=document, headers=auth_headers).json()
    novel = db.query(Novel).filter(Novel.url == RR.format(77, 77)).one()
    assert novel.metadata_id is None and novel.scrape_status == "pending"
    asyncio.run(imports.run_import_job(imported["import_job_ids"][0], TestingSessionLocal, scrape=FakeScrape()))
    db.expire_all()
    novel = db.query(Novel).filter(Novel.url == RR.format(77, 77)).one()
    assert novel.metadata_id is not None and novel.scrape_status == "completed"


def test_cancel_and_ownership(client, db, test_library, auth_headers, monkeypatch):
    job = client.post("/imports/urls", json={"library_id": test_library.id, "text": FFN.format(1)}, headers=auth_headers).json()
    cancelled = client.post(f"/imports/{job['id']}/cancel", headers=auth_headers).json()
    assert cancelled["status"] == "cancelled"
    assert imports.next_job_id(db) is None
    assert client.get("/imports/999999", headers=auth_headers).status_code == 404
    assert [row["id"] for row in client.get("/imports", headers=auth_headers).json()] == [job["id"]]
    assert db.get(ImportJob, job["id"]).items[0].status == "queued"


@pytest.mark.parametrize("text", ["", "no links here"])
def test_url_import_needs_urls(client, test_library, auth_headers, text):
    response = client.post("/imports/urls", json={"library_id": test_library.id, "text": text}, headers=auth_headers)
    assert response.status_code == 422
