import io
import zipfile
from datetime import datetime
from unittest.mock import MagicMock, patch

import httpx

from app.models.chapter import Chapter
from app.models.library import Library
from app.models.novel import Novel
from app.models.novel_personal import NovelPersonalData
from app.models.reading_annotation import ReadingAnnotation
from app.models.readwise import ReadwiseConnection
from app.models.user import User
from tests import auth_helpers

TOKEN = "readwise-token-123456"
VERIFY = "app.services.highlights_export_service.httpx.get"
POST = "app.services.highlights_export_service.httpx.post"


def _response(status: int):
    response = MagicMock()
    response.status_code = status
    return response


def _story(db, user, title="Mother of Learning", library=None, source="https://www.royalroad.com/fiction/21220"):
    if library is None:
        library = Library(name=f"{title} lib", user_id=user.id)
        db.add(library)
        db.flush()
    novel = Novel(title=title, author="ThePotatoOfDoom", site="royalroad", source_url=source, library_id=library.id, rating=3)
    db.add(novel)
    db.flush()
    chapter_two = Chapter(novel_id=novel.id, chapter_number=2, title="Chapter 2: Second", source_url=f"{source}/chapter-2")
    chapter_one = Chapter(novel_id=novel.id, chapter_number=1, title="Chapter 1: First", source_url=f"{source}/chapter-1")
    db.add_all([chapter_two, chapter_one])
    db.flush()
    db.add(NovelPersonalData(user_id=user.id, novel_id=novel.id, notes="Re-read the loop logic", rating=5))
    db.add(ReadingAnnotation(user_id=user.id, novel_id=novel.id, chapter_id=chapter_two.id, annotation_type="highlight",
                             position=5, percent=10, quote="Second line\nsecond paragraph", note="Foreshadowing",
                             created_at=datetime(2026, 9, 2, 10, 0)))
    db.add(ReadingAnnotation(user_id=user.id, novel_id=novel.id, chapter_id=chapter_one.id, annotation_type="highlight",
                             position=1, percent=1, quote="First quote", note=None, created_at=datetime(2026, 9, 1, 10, 0)))
    db.add(ReadingAnnotation(user_id=user.id, novel_id=novel.id, chapter_id=chapter_one.id, annotation_type="bookmark",
                             position=2, percent=2, quote=None, note=None))
    db.commit()
    return novel


def test_export_requires_authentication(client):
    assert client.get("/export/highlights").status_code == 401
    assert client.get("/export/readwise").status_code == 401


def test_single_story_markdown_has_front_matter_notes_and_grouped_highlights(client, auth_headers, db, test_user):
    novel = _story(db, test_user)

    response = client.get(f"/export/highlights?format=markdown&novel_id={novel.id}", headers=auth_headers)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    body = response.text
    assert body.startswith("---\ntitle: \"Mother of Learning\"\n")
    assert 'author: "ThePotatoOfDoom"' in body
    assert 'source_url: "https://www.royalroad.com/fiction/21220"' in body
    assert "rating: 5" in body
    assert "## Notes\n\nRe-read the loop logic" in body
    assert "### [Chapter 1: First](https://www.royalroad.com/fiction/21220/chapter-1)" in body
    assert "> First quote" in body
    assert "> Second line\n> second paragraph" in body
    assert "Foreshadowing" in body
    assert body.index("Chapter 1: First") < body.index("Chapter 2: Second")
    assert body.count("###") == 2


def test_bookmarks_are_not_exported(client, auth_headers, db, test_user):
    novel = _story(db, test_user)

    body = client.get(f"/export/highlights?format=markdown&novel_id={novel.id}", headers=auth_headers).text

    assert body.count("> ") == 3


def test_no_novel_id_returns_zip_with_one_file_per_story(client, auth_headers, db, test_user):
    _story(db, test_user, title="Mother: of/Learning")
    _story(db, test_user, title="Second Story", source="https://example.test/2")

    response = client.get("/export/highlights", headers=auth_headers)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert sorted(archive.namelist()) == ["Mother of Learning.md", "Second Story.md"]
        assert "> First quote" in archive.read("Mother of Learning.md").decode()


def test_export_is_scoped_to_the_requesting_user(client, auth_headers, db, test_user):
    other = User(username="intruder", password="x")
    db.add(other)
    db.commit()
    foreign = _story(db, other, title="Private Story")

    assert client.get(f"/export/highlights?format=markdown&novel_id={foreign.id}", headers=auth_headers).status_code == 404
    zipped = client.get("/export/highlights", headers=auth_headers)
    with zipfile.ZipFile(io.BytesIO(zipped.content)) as archive:
        assert archive.namelist() == []


def test_json_format_lists_highlights_with_chapter_links(client, auth_headers, db, test_user):
    novel = _story(db, test_user)

    stories = client.get(f"/export/highlights?format=json&novel_id={novel.id}", headers=auth_headers).json()

    assert len(stories) == 1
    assert stories[0]["notes"] == "Re-read the loop logic"
    assert stories[0]["rating"] == 5
    assert [h["quote"] for h in stories[0]["highlights"]] == ["First quote", "Second line\nsecond paragraph"]
    assert stories[0]["highlights"][0]["chapter_url"].endswith("/chapter-1")


def test_unknown_novel_is_not_found(client, auth_headers):
    assert client.get("/export/highlights?novel_id=9999", headers=auth_headers).status_code == 404


def test_readwise_connect_stores_token_encrypted_and_reports_status(client, auth_headers, db):
    with patch(VERIFY, return_value=_response(204)):
        response = client.put("/export/readwise", json={"token": TOKEN}, headers=auth_headers)

    assert response.status_code == 200
    stored = db.query(ReadwiseConnection).one()
    assert TOKEN not in stored.token_encrypted
    assert client.get("/export/readwise", headers=auth_headers).json() == {"connected": True}


def test_readwise_rejects_invalid_token(client, auth_headers, db):
    with patch(VERIFY, return_value=_response(401)):
        response = client.put("/export/readwise", json={"token": TOKEN}, headers=auth_headers)

    assert response.status_code == 422
    assert db.query(ReadwiseConnection).count() == 0


def test_readwise_network_failure_is_a_clean_502(client, auth_headers):
    with patch(VERIFY, side_effect=httpx.ConnectError("boom")):
        response = client.put("/export/readwise", json={"token": TOKEN}, headers=auth_headers)

    assert response.status_code == 502
    assert response.json()["detail"] == "Readwise could not be reached"


def test_readwise_sync_sends_highlights_once(client, auth_headers, db, test_user):
    novel = _story(db, test_user)
    with patch(VERIFY, return_value=_response(204)):
        client.put("/export/readwise", json={"token": TOKEN}, headers=auth_headers)

    with patch(POST, return_value=_response(201)) as post:
        first = client.post("/export/readwise/sync", json={"novel_id": novel.id}, headers=auth_headers)
        second = client.post("/export/readwise/sync", json={"novel_id": novel.id}, headers=auth_headers)

    assert first.json() == {"exported": 2}
    assert second.json() == {"exported": 0}
    assert post.call_count == 1
    url = post.call_args.args[0]
    assert url == "https://readwise.io/api/v2/highlights/"
    assert post.call_args.kwargs["headers"] == {"Authorization": f"Token {TOKEN}"}
    sent = post.call_args.kwargs["json"]["highlights"]
    assert sent[0]["text"] == "First quote"
    assert sent[0]["location_type"] == "order"
    assert sent[0]["category"] == "books"
    assert sent[0]["title"] == "Mother of Learning"
    assert sent[0]["source_url"].endswith("/chapter-1")
    assert sent[1]["note"] == "Foreshadowing"
    assert sent[0]["highlighted_at"].startswith("2026-09-01")
    assert db.query(ReadingAnnotation).filter(ReadingAnnotation.exported_at.is_(None), ReadingAnnotation.annotation_type == "highlight").count() == 0


def test_readwise_sync_failure_keeps_annotations_pending(client, auth_headers, db, test_user):
    _story(db, test_user)
    with patch(VERIFY, return_value=_response(204)):
        client.put("/export/readwise", json={"token": TOKEN}, headers=auth_headers)

    with patch(POST, side_effect=httpx.ReadTimeout("slow")):
        response = client.post("/export/readwise/sync", json={}, headers=auth_headers)

    assert response.status_code == 502
    assert db.query(ReadingAnnotation).filter(ReadingAnnotation.exported_at.is_(None), ReadingAnnotation.annotation_type == "highlight").count() == 2


def test_sync_without_connection_conflicts(client, auth_headers):
    assert client.post("/export/readwise/sync", json={}, headers=auth_headers).status_code == 409


def test_disconnect_removes_token(client, auth_headers, db):
    with patch(VERIFY, return_value=_response(204)):
        client.put("/export/readwise", json={"token": TOKEN}, headers=auth_headers)

    assert client.delete("/export/readwise", headers=auth_headers).status_code == 204
    assert client.get("/export/readwise", headers=auth_headers).json() == {"connected": False}
