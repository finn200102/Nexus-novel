from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.auth.jwt import create_access_token
from app.models.chapter import Chapter
from app.models.follow import UserNovelFollow
from app.models.library import Library
from app.models.novel import Novel
from app.models.reading_annotation import ReadingAnnotation
from app.models.reading_history import ReadingHistory
from app.models.reading_progress import ReadingProgress
from app.models.saved_search import SavedSearch
from app.models.user import User

ROYAL_ROAD_URL = "https://www.royalroad.com/fiction/21220/mother-of-learning"


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token({'sub': str(user.id)})}"}


@pytest.fixture
def scrape(monkeypatch):
    """Metadata calls are mocked; the background scrape is recorded, not run."""
    scrape_call = AsyncMock(return_value={"success": True, "novel_id": 99, "message": "ok"})
    background = MagicMock()
    monkeypatch.setattr("app.services.metadata_client.scrape_novel_by_url", scrape_call)
    monkeypatch.setattr("app.routers.user_data.scrape_novel_background", background)
    return scrape_call, background


def _add_chapters(db, novel: Novel, count: int = 3) -> list[Chapter]:
    chapters = [
        Chapter(novel_id=novel.id, chapter_number=number, title=f"Chapter {number}")
        for number in range(1, count + 1)
    ]
    db.add_all(chapters)
    db.commit()
    return chapters


def _seed(db, user: User) -> Novel:
    library = Library(name="Reading", user_id=user.id)
    db.add(library)
    db.flush()
    novel = Novel(
        title="Mother of Learning",
        url=ROYAL_ROAD_URL,
        library_id=library.id,
        novel_site="royalroad",
        metadata_id=11,
        follow_state="reading",
        followed_at=datetime(2026, 9, 1, 12, 0),
    )
    db.add(novel)
    db.commit()
    chapters = _add_chapters(db, novel)

    db.add(UserNovelFollow(user_id=user.id, novel_id=novel.id, state="reading", followed_at=datetime(2026, 9, 1, 12, 0)))
    db.add(ReadingProgress(user_id=user.id, novel_id=novel.id, chapter_id=chapters[1].id, chapter_number=2, position=120, percent=45.5))
    db.add(ReadingHistory(user_id=user.id, novel_id=novel.id, chapter_number=1, reading_date=datetime(2026, 9, 30), max_percent=100))
    db.add(ReadingHistory(user_id=user.id, novel_id=novel.id, chapter_number=2, reading_date=datetime(2026, 10, 1), max_percent=45))
    db.add(ReadingAnnotation(
        user_id=user.id,
        novel_id=novel.id,
        chapter_id=chapters[0].id,
        annotation_type="note",
        position=10,
        percent=5.0,
        quote="A quote worth keeping",
        note="Remember this",
    ))
    db.add(SavedSearch(user_id=user.id, name="Time loops", filters={"tags": ["time loop"]}, notify_on_match=True))
    db.commit()
    return novel


def _wipe(db, user: User) -> None:
    for model in (ReadingProgress, ReadingHistory, ReadingAnnotation, UserNovelFollow, SavedSearch):
        db.query(model).filter(model.user_id == user.id).delete()
    for library in db.query(Library).filter(Library.user_id == user.id).all():
        db.delete(library)
    db.commit()


def _comparable(document: dict) -> dict:
    """Drop fields that legitimately differ between instances.

    ``exported_at`` is a timestamp, and ``metadata_id`` is a local catalog id
    that the import re-resolves on the target instance.
    """
    copied = {key: value for key, value in document.items() if key != "exported_at"}
    copied["libraries"] = [
        {
            **library,
            "novels": [{key: value for key, value in novel.items() if key != "metadata_id"} for novel in library["novels"]],
        }
        for library in document["libraries"]
    ]
    return copied


def _row_counts(db, user: User) -> dict[str, int]:
    return {
        "novels": db.query(Novel).count(),
        "progress": db.query(ReadingProgress).filter(ReadingProgress.user_id == user.id).count(),
        "history": db.query(ReadingHistory).filter(ReadingHistory.user_id == user.id).count(),
        "annotations": db.query(ReadingAnnotation).filter(ReadingAnnotation.user_id == user.id).count(),
        "follows": db.query(UserNovelFollow).filter(UserNovelFollow.user_id == user.id).count(),
        "saved_searches": db.query(SavedSearch).filter(SavedSearch.user_id == user.id).count(),
        "libraries": db.query(Library).filter(Library.user_id == user.id).count(),
    }


def test_export_requires_authentication(client):
    assert client.get("/me/export").status_code == 401


def test_export_is_versioned_and_keyed_by_source_url(client, db, test_user):
    _seed(db, test_user)

    response = client.get("/me/export", headers=_headers(test_user))

    assert response.status_code == 200
    assert response.headers["content-disposition"].startswith("attachment; filename=\"nexus-export-")
    document = response.json()
    assert document["format"] == "nexus-user-export"
    assert document["version"] == 1
    novel = document["libraries"][0]["novels"][0]
    assert novel["url"] == ROYAL_ROAD_URL
    assert novel["follow_state"] == "reading"
    assert novel["progress"] == {"chapter_number": 2, "position": 120, "percent": 45.5}
    assert novel["history"] == [
        {"chapter_number": 1, "date": "2026-09-30", "max_percent": 100},
        {"chapter_number": 2, "date": "2026-10-01", "max_percent": 45},
    ]
    assert novel["annotations"][0]["chapter_number"] == 1
    assert "novel_id" not in response.text and '"id"' not in response.text
    assert document["saved_searches"] == [{"name": "Time loops", "filters": {"tags": ["time loop"]}, "notify_on_match": True}]


def test_export_wipe_import_round_trip_restores_equal_content(client, db, test_user, scrape):
    scrape_call, background = scrape
    _seed(db, test_user)
    exported = client.get("/me/export", headers=_headers(test_user)).json()

    _wipe(db, test_user)
    assert _row_counts(db, test_user)["libraries"] == 0

    first = client.post("/me/import", json=exported, headers=_headers(test_user))
    assert first.status_code == 200, first.text
    report = first.json()
    assert report["summary"]["libraries_created"] == 1
    assert report["summary"]["novels_created"] == 1
    # Chapters arrive with the background scrape, so annotations wait for them.
    assert report["summary"]["annotations_deferred"] == 1
    scrape_call.assert_awaited_once_with(ROYAL_ROAD_URL, "royalroad")
    background.assert_called_once()

    novel = db.query(Novel).filter(Novel.url == ROYAL_ROAD_URL).one()
    _add_chapters(db, novel)  # simulates the scrape finishing

    second = client.post("/me/import", json=exported, headers=_headers(test_user))
    assert second.status_code == 200, second.text
    assert second.json()["summary"]["annotations_added"] == 1
    assert second.json()["summary"]["annotations_deferred"] == 0

    again = client.get("/me/export", headers=_headers(test_user)).json()
    assert _comparable(again) == _comparable(exported)


def test_import_twice_creates_no_duplicates(client, db, test_user, scrape):
    _seed(db, test_user)
    exported = client.get("/me/export", headers=_headers(test_user)).json()
    _wipe(db, test_user)

    client.post("/me/import", json=exported, headers=_headers(test_user))
    novel = db.query(Novel).filter(Novel.url == ROYAL_ROAD_URL).one()
    _add_chapters(db, novel)
    client.post("/me/import", json=exported, headers=_headers(test_user))
    counts_after_second = _row_counts(db, test_user)

    third = client.post("/me/import", json=exported, headers=_headers(test_user))

    assert third.status_code == 200
    summary = third.json()["summary"]
    assert summary["libraries_created"] == 0
    assert summary["novels_created"] == 0
    assert summary["novels_linked"] == 1
    assert summary["history_added"] == 0
    assert summary["annotations_added"] == 0
    assert summary["progress_applied"] == 0
    assert summary["follow_states_updated"] == 0
    assert summary["saved_searches_created"] == 0
    assert _row_counts(db, test_user) == counts_after_second


def test_import_relinks_existing_novel_by_url_without_scraping(client, db, test_user, scrape):
    scrape_call, background = scrape
    _seed(db, test_user)
    exported = client.get("/me/export", headers=_headers(test_user)).json()

    response = client.post("/me/import", json=exported, headers=_headers(test_user))

    assert response.status_code == 200
    assert response.json()["libraries"][0]["novels"][0]["status"] == "linked"
    scrape_call.assert_not_awaited()
    background.assert_not_called()
    assert db.query(Novel).count() == 1


def test_import_keeps_furthest_progress(client, db, test_user, scrape):
    _seed(db, test_user)
    document = {
        "format": "nexus-user-export",
        "version": 1,
        "libraries": [{
            "name": "Reading",
            "novels": [{
                "url": ROYAL_ROAD_URL,
                "progress": {"chapter_number": 1, "position": 5, "percent": 99},
            }],
        }],
    }

    response = client.post("/me/import", json=document, headers=_headers(test_user))

    assert response.status_code == 200
    assert response.json()["libraries"][0]["novels"][0]["progress"] == "unchanged"
    progress = db.query(ReadingProgress).filter(ReadingProgress.user_id == test_user.id).one()
    assert (progress.chapter_number, progress.percent) == (2, 45.5)


def test_import_keeps_local_saved_search_on_conflict(client, db, test_user, scrape):
    _seed(db, test_user)
    document = {
        "format": "nexus-user-export",
        "version": 1,
        "saved_searches": [{"name": "Time loops", "filters": {"tags": ["isekai"]}, "notify_on_match": False}],
    }

    response = client.post("/me/import", json=document, headers=_headers(test_user))

    assert response.json()["saved_searches"] == [{"name": "Time loops", "status": "conflict"}]
    search = db.query(SavedSearch).filter(SavedSearch.user_id == test_user.id).one()
    assert search.filters == {"tags": ["time loop"]}


def test_import_rejects_unsupported_version(client, test_user, scrape):
    document = {"format": "nexus-user-export", "version": 2, "libraries": []}

    response = client.post("/me/import", json=document, headers=_headers(test_user))

    assert response.status_code == 422
    assert "Unsupported export version 2" in response.json()["detail"]


def test_import_rejects_foreign_format(client, test_user, scrape):
    document = {"format": "something-else", "version": 1, "libraries": []}

    response = client.post("/me/import", json=document, headers=_headers(test_user))

    assert response.status_code == 422


def test_import_reports_unsupported_source_per_novel(client, test_user, scrape):
    scrape_call, _ = scrape
    document = {
        "format": "nexus-user-export",
        "version": 1,
        "libraries": [{"name": "Imported", "novels": [{"url": "https://example.com/story/1"}]}],
    }

    response = client.post("/me/import", json=document, headers=_headers(test_user))

    assert response.status_code == 200
    novel_report = response.json()["libraries"][0]["novels"][0]
    assert novel_report["status"] == "failed"
    assert novel_report["reason"] == "Not a supported source url"
    scrape_call.assert_not_awaited()
