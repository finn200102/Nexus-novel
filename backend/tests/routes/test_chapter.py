import pytest
from fastapi import status
from app.services.novel_services import (
    create_novel,
)
from app.services.chapter_services import (
    get_chapters_by_novel_id,
    get_chapter_by_id,
)
from app.services.library_services import create_library
from app.services.user_services import create_user
from tests.auth_helpers import bearer_headers
from app.routers.chapter import extract_story_id_from_url
from app.models.download_job import ChapterDownloadJob
from app.models.chapter import Chapter, ContentStatus
from app.services.download_job_service import retry_job
from app.routers.chapter import run_queued_download
from tests.routes.conftest import TestingSessionLocal


def create_test_user(db):
    user_data = {}
    user_data["username"] = "user1"
    user_data["password"] = "1234"
    user = create_user(db, user_data)
    return user


def create_test_library(db):
    user = create_test_user(db)
    library_data = {"name": "Library1", "user_id": user.id}
    library = create_library(db, library_data)
    return library


def create_test_novel(db):
    # Test data
    url = "https://www.royalroad.com/fiction/21220/mother-of-learning"
    novel_data = {"url": url, "title": "title1"}
    # create lib
    library = create_test_library(db)
    novel_data["library_id"] = library.id
    novel = create_novel(db, novel_data)
    # get auth header
    user_id = library.user_id
    headers = get_auth_headers(user_id)

    return novel, headers, novel_data, url, library


def get_auth_headers(user_id):
    """Generate authorization headers for a user"""
    return bearer_headers(user_id)


def test_manual_download_retry_starts_a_new_attempt_cycle(db):
    job = ChapterDownloadJob(
        user_id=1,
        library_id=1,
        novel_id=1,
        chapter_id=1,
        status="failed",
        attempt_count=3,
        max_attempts=3,
        error="old source error",
    )
    db.add(job)
    db.commit()

    retry_job(db, job)
    db.refresh(job)

    assert job.status == "queued"
    assert job.attempt_count == 0
    assert job.error is None


def add_chapter(client, novel_id, headers):
    # Chapter
    chapter_data = {
        "novel_id": novel_id,
        "chapter_number": 1,
        "title": "aaa",
        "content_status": "MISSING",
    }

    response = client.post("/chapter/", json=chapter_data, headers=headers)
    return response


def test_add_chapter(client, db):
    novel, headers, novel_data, url, library = create_test_novel(db)
    response = add_chapter(client, novel.id, headers)

    assert response.status_code == status.HTTP_201_CREATED

    chapters = get_chapters_by_novel_id(db, novel.id)
    print(chapters.first())
    assert chapters.first() is not None


def test_get_chapters(client, db):
    novel, headers, novel_data, url, library = create_test_novel(db)
    response = add_chapter(client, novel.id, headers)

    # get chapter
    response = client.get(f"/chapter/{novel.id}", headers=headers)
    print("Response status:", response.status_code)
    print("Response JSON:", response.json())

    # Assertions for the GET request
    chapters = response.json()
    assert chapters is not None
    print(chapters)

    # Verify the created chapter is in the response
    found = False
    for chapter in chapters:
        if chapter["title"] == "aaa":
            found = True
            break
    assert found, "Created chapter not found in the response"


def test_get_chapter_by_number(client, db):
    novel, headers, novel_data, url, library = create_test_novel(db)
    response = add_chapter(client, novel.id, headers)
    chapter_number = response.json()["chapter_number"]
    # get chapter by number
    response = client.get(f"/chapter/{novel.id}/{chapter_number}", headers=headers)
    print("Response status:", response.status_code)
    print("Response JSON:", response.json())
    chapter = response.json()
    assert chapter["title"] == "aaa"


def test_delete_chapter_by_id(client, db):
    novel, headers, novel_data, url, library = create_test_novel(db)
    response = add_chapter(client, novel.id, headers)
    chapter_id = response.json()["id"]

    response = client.delete(f"chapter/{chapter_id}", headers=headers)

    chapter = get_chapter_by_id(db, chapter_id)
    print(chapter)
    assert chapter is None


def test_update_chapter(client, db):
    novel, headers, novel_data, url, library = create_test_novel(db)
    response = add_chapter(client, novel.id, headers)
    chapter_id = response.json()["id"]
    chapter_data = {
        "novel_id": novel.id,
        "chapter_number": 1,
        "title": "aaa",
        "content_status": "PRESENT",
        "id": chapter_id,
    }
    response = client.put("/chapter/", json=chapter_data, headers=headers)
    chapter = get_chapter_by_id(db, chapter_id)
    print(chapter)
    assert chapter is not None
    assert chapter.content_status.value == "PRESENT"


def test_get_downloaded_chapter_content(client, db):
    novel, headers, _, _, library = create_test_novel(db)
    response = add_chapter(client, novel.id, headers)
    chapter = get_chapter_by_id(db, response.json()["id"])
    chapter.content = "First paragraph.\n\nSecond paragraph."
    chapter.content_status = "PRESENT"
    db.commit()

    response = client.get(
        f"/chapter/content/library/{library.id}/{novel.id}/1", headers=headers
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["content"] == "First paragraph.\n\nSecond paragraph."


def test_queued_download_delegates_to_metadata_server(client, db, monkeypatch):
    novel, _, _, _, library = create_test_novel(db)
    novel.metadata_id = 9876
    response = add_chapter(client, novel.id, get_auth_headers(library.user_id))
    chapter_id = response.json()["id"]
    job = ChapterDownloadJob(
        user_id=library.user_id,
        library_id=library.id,
        novel_id=novel.id,
        chapter_id=chapter_id,
        status="queued",
        max_attempts=3,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    calls = []

    def fake_fetch(metadata_id, chapter_number):
        calls.append((metadata_id, chapter_number))
        return {"title": "Downloaded title", "text": "Downloaded through Nexus Server."}

    monkeypatch.setattr(
        "app.services.metadata_client.fetch_public_chapter_text_sync", fake_fetch
    )

    run_queued_download(job.id, TestingSessionLocal)

    db.expire_all()
    downloaded = db.query(Chapter).filter(Chapter.id == chapter_id).one()
    completed_job = db.query(ChapterDownloadJob).filter(ChapterDownloadJob.id == job.id).one()
    assert calls == [(9876, 1)]
    assert downloaded.content == "Downloaded through Nexus Server."
    assert downloaded.content_status == ContentStatus.PRESENT
    assert completed_job.status == "completed"


def test_chapter_router_has_no_runtime_pybindings_dependency():
    import inspect
    import app.routers.chapter as chapter_router

    source = inspect.getsource(chapter_router)
    assert "pybindings" not in source
    assert "novel_downloader" not in source


@pytest.mark.parametrize(
    ("url", "site", "expected"),
    [
        ("https://www.fanfiction.net/s/6928484", "fanfiction", 6928484),
        ("https://www.fanfiction.net/s/5782108/1/title", "fanfiction", 5782108),
        ("https://www.royalroad.com/fiction/65629/the-game-at-carousel", "royalroad", 65629),
        ("https://forums.spacebattles.com/threads/story-name.428998", "spacebattles", 428998),
        ("https://forums.spacebattles.com/threads/428998/", "spacebattles", 428998),
        ("https://archiveofourown.org/works/12345/chapters/67890", "archive", 12345),
        ("https://www.webnovel.com/book/example_12345", "webnovel", 12345),
    ],
)
def test_extract_story_id_from_supported_source_urls(url, site, expected):
    assert extract_story_id_from_url(url, site) == expected


def test_extract_story_id_rejects_unknown_or_invalid_urls():
    assert extract_story_id_from_url("https://example.test/works/123", "unknown") is None
    assert extract_story_id_from_url("https://www.royalroad.com/fictions/123", "royalroad") is None


def test_queue_chapter_downloads_persists_jobs(client, db, monkeypatch):
    novel, headers, _, _, library = create_test_novel(db)
    for chapter_number in (1, 2, 3):
        response = client.post(
            "/chapter/",
            json={
                "novel_id": novel.id,
                "chapter_number": chapter_number,
                "title": f"Chapter {chapter_number}",
                "content_status": "MISSING",
            },
            headers=headers,
        )
        assert response.status_code == status.HTTP_201_CREATED

    monkeypatch.setattr("app.routers.chapter.run_queued_download", lambda *_args: None)
    response = client.post(
        f"/chapter/queue/{library.id}/{novel.id}",
        json={"count": 2},
        headers=headers,
    )
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 2
    assert all(job["status"] == "queued" for job in response.json())

    response = client.get(f"/chapter/queue/{novel.id}", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 2


def test_reading_progress_is_persisted_per_user(client, db):
    novel, headers, _, _, _ = create_test_novel(db)
    add_chapter(client, novel.id, headers)

    response = client.put(
        f"/chapter/progress/{novel.id}",
        json={"chapter_number": 1, "position": 240, "percent": 37.5},
        headers=headers,
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["position"] == 240
    assert response.json()["percent"] == 37.5

    response = client.get(f"/chapter/progress/{novel.id}", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["chapter_number"] == 1


def test_reading_annotations_are_private_and_positioned(client, db):
    novel, headers, _, _, _ = create_test_novel(db)
    add_chapter(client, novel.id, headers)

    response = client.post(
        f"/chapter/annotations/{novel.id}",
        json={
            "chapter_number": 1,
            "annotation_type": "note",
            "position": 120,
            "percent": 18.5,
            "quote": "A memorable line",
            "note": "Follow this thread later",
        },
        headers=headers,
    )
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["chapter_number"] == 1
    assert response.json()["note"] == "Follow this thread later"

    response = client.get(f"/chapter/annotations/{novel.id}", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 1

    response = client.delete(
        f"/chapter/annotations/{response.json()[0]['id']}", headers=headers
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT
