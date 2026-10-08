from app.models.user import User
from fastapi import status
from app.services.novel_services import get_novel_by_url
from app.services.library_services import create_library
from app.services.user_services import create_user
from tests.auth_helpers import bearer_headers


def create_test_user(db):
    # Reuse the account when a test asks for it twice: usernames are unique.
    existing = db.query(User).filter(User.username == "user1").first()
    if existing:
        return existing
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


def get_auth_headers(user_id):
    """Generate authorization headers for a user"""
    return bearer_headers(user_id)


def add_novel_resources(client, db):
    # Test data
    url = "https://www.royalroad.com/fiction/21220/mother-of-learning"
    novel_data = {"url": url}
    # create lib
    library = create_test_library(db)
    novel_data["library_id"] = library.id

    # get auth header
    user_id = library.user_id
    headers = get_auth_headers(user_id)

    # Make request
    response = client.post("/novel/", json=novel_data, headers=headers)

    return response, headers, novel_data, url, library


def test_add_novel(client_with_auth, db):
    response, headers, novel_data, url, library = add_novel_resources(
        client_with_auth, db
    )

    # Assertions
    assert response.status_code == status.HTTP_201_CREATED

    # Verify nove was created
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is not None
    assert db_novel.url == url


def test_add_novel_is_idempotent_for_same_library(client_with_auth, db):
    first_response, headers, novel_data, url, library = add_novel_resources(
        client_with_auth, db
    )

    second_response = client_with_auth.post(
        "/novel/", json=novel_data, headers=headers
    )

    assert first_response.status_code == status.HTTP_201_CREATED
    assert second_response.status_code == status.HTTP_201_CREATED
    assert second_response.json()["id"] == first_response.json()["id"]


def test_add_novel_to_a_second_library(client_with_auth, db):
    first_response, headers, novel_data, url, library = add_novel_resources(
        client_with_auth, db
    )
    second_library = create_library(
        db, {"name": "Library2", "user_id": library.user_id}
    )

    second_response = client_with_auth.post(
        "/novel/", json={"url": url, "library_id": second_library.id}, headers=headers
    )

    assert first_response.status_code == status.HTTP_201_CREATED
    assert second_response.status_code == status.HTTP_201_CREATED
    assert second_response.json()["id"] != first_response.json()["id"]
    assert second_response.json()["library_id"] == second_library.id


def test_add_novel_unauthorized(client_with_auth, db):
    """Test that adding a novel fails without authentication"""
    # Create a user and library
    create_test_user(db)
    library = create_test_library(db)

    # Test data
    url = "https://www.royalroad.com/fiction/21220/mother-of-learning"
    novel_data = {"url": url, "library_id": library.id}

    # Make request without auth
    response = client_with_auth.post("/novel/", json=novel_data)

    # Should fail with 401 Unauthorized
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    # Verify novel was not created
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is None


def test_get_novels(client_with_auth, db):
    response, headers, novel_data, url, library = add_novel_resources(
        client_with_auth, db
    )

    # Assertions
    assert response.status_code == status.HTTP_201_CREATED

    # Verify nove was created
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is not None
    assert db_novel.url == url

    # get novel
    response = client_with_auth.get(f"/novel/?library_id={library.id}", headers=headers)
    print("Response status:", response.status_code)
    print("Response JSON:", response.json())

    # Assertions for the GET request
    assert response.status_code == 200
    novels = response.json()
    assert novels is not None
    assert len(novels) > 0

    # Verify the created novel is in the response
    found = False
    for novel in novels:
        if novel["url"] == url:
            found = True
            break
    assert found, "Created novel not found in the response"


def test_get_novel_by_id(client_with_auth, db):
    response, headers, novel_data, url, library = add_novel_resources(
        client_with_auth, db
    )

    # Assertions
    assert response.status_code == status.HTTP_201_CREATED

    # Verify nove was created
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is not None
    assert db_novel.url == url

    # get novel
    response = client_with_auth.get(
        f"/novel/{db_novel.id}?library_id={library.id}", headers=headers
    )
    print("Response status:", response.status_code)
    print("Response JSON:", response.json())

    # Assertions for the GET request
    assert response.status_code == 200
    novel = response.json()
    assert novel is not None
    assert novel["id"] == db_novel.id


def test_delete_novel_by_id(client_with_auth, db):
    response, headers, novel_data, url, library = add_novel_resources(
        client_with_auth, db
    )

    # Assertions
    assert response.status_code == status.HTTP_201_CREATED

    # Verify nove was created
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is not None

    # delete novel
    response = client_with_auth.post(
        f"/novel/delete/{db_novel.id}?library_id={library.id}", headers=headers
    )

    # Verify nove was deleted
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is None


def test_update_novel(client_with_auth, db):
    response, headers, novel_data, url, library = add_novel_resources(
        client_with_auth, db
    )

    # Assertions
    assert response.status_code == status.HTTP_201_CREATED

    # Verify nove was created
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is not None
    new_novel_data = novel_data
    new_novel_data["id"] = db_novel.id
    new_novel_data["title"] = "newtitle"

    # update novel
    response = client_with_auth.post(
        "/novel/update", json=new_novel_data, headers=headers
    )

    # Verify nove was updated
    db_novel = get_novel_by_url(db, url).first()
    assert db_novel is not None
    assert db_novel.title == "newtitle"


def test_update_follow_state(client_with_auth, db):
    response, headers, _, url, library = add_novel_resources(client_with_auth, db)
    assert response.status_code == status.HTTP_201_CREATED
    novel = get_novel_by_url(db, url).first()
    assert novel is not None

    response = client_with_auth.patch(
        f"/novel/{novel.id}/follow?library_id={library.id}",
        json={
            "follow_state": "reading",
            "download_policy": "next_n",
            "download_count": 5,
            "notification_policy": "daily_digest",
        },
        headers=headers,
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["follow_state"] == "reading"

    response = client_with_auth.get(
        f"/novel/{novel.id}/follow?library_id={library.id}",
        headers=headers,
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["download_policy"] == "next_n"
    assert response.json()["download_count"] == 5
    assert response.json()["notification_policy"] == "daily_digest"


def test_export_epub_contains_downloaded_chapters(client_with_auth, db):
    from app.models.chapter import Chapter, ContentStatus

    response, headers, _, url, library = add_novel_resources(client_with_auth, db)
    assert response.status_code == status.HTTP_201_CREATED
    novel = get_novel_by_url(db, url).first()
    chapter = db.query(Chapter).filter(Chapter.novel_id == novel.id).first()
    chapter.content_status = ContentStatus.PRESENT
    chapter.content = "A downloaded chapter."
    chapter.title = "Chapter One"
    db.commit()

    response = client_with_auth.get(f"/chapter/novel/{novel.id}/export.epub", headers=headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"].startswith("application/epub+zip")
    assert response.content[:2] == b"PK"


def test_metadata_refresh_event_creates_user_event_and_download_job(client_with_auth, db, monkeypatch):
    from app.models.download_job import ChapterDownloadJob
    from app.models.update_event import NovelUpdateEvent

    response, headers, _, url, library = add_novel_resources(client_with_auth, db)
    assert response.status_code == status.HTTP_201_CREATED
    novel = get_novel_by_url(db, url).first()
    novel.metadata_id = 77
    db.commit()
    response = client_with_auth.patch(
        f"/novel/{novel.id}/follow?library_id={library.id}",
        json={
            "follow_state": "reading",
            "download_policy": "next_n",
            "download_count": 2,
            "notification_policy": "immediate",
        },
        headers=headers,
    )
    assert response.status_code == status.HTTP_200_OK
    monkeypatch.setenv("NEXUS_NOVEL_WEBHOOK_SECRET", "test-secret")
    response = client_with_auth.post(
        "/novel/internal/metadata-events",
        headers={"X-Nexus-Webhook-Secret": "test-secret"},
        json={
            "event": "source_refresh_completed",
            "job_id": "job-1",
            "metadata_novel_id": 77,
            "source_id": 9,
            "site": "royalroad",
            "new_chapter_numbers": [11, 12, 13],
            "chapters": [
                {"chapter_number": 11, "chapter_id": 11, "title": "Eleven"},
                {"chapter_number": 12, "chapter_id": 12, "title": "Twelve"},
                {"chapter_number": 13, "chapter_id": 13, "title": "Thirteen"},
            ],
        },
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["created_events"] == 1
    assert response.json()["queued_downloads"] == 2
    assert db.query(NovelUpdateEvent).filter(NovelUpdateEvent.novel_id == novel.id).count() == 1
    # Two known chapters were queued when the policy was applied, and two of
    # the newly reported chapters were queued by the refresh event.
    assert db.query(ChapterDownloadJob).filter(ChapterDownloadJob.novel_id == novel.id).count() == 4


def test_metadata_refresh_event_duplicate_is_noop(client_with_auth, db, monkeypatch):
    from app.models.download_job import ChapterDownloadJob
    from app.models.metadata_webhook_delivery import MetadataWebhookDelivery
    from app.models.update_event import NovelUpdateEvent

    response, headers, _, url, library = add_novel_resources(client_with_auth, db)
    assert response.status_code == status.HTTP_201_CREATED
    novel = get_novel_by_url(db, url).first()
    novel.metadata_id = 78
    db.commit()
    client_with_auth.patch(
        f"/novel/{novel.id}/follow?library_id={library.id}",
        json={"follow_state": "reading", "download_policy": "next_chapter"},
        headers=headers,
    )
    monkeypatch.setenv("NEXUS_NOVEL_WEBHOOK_SECRET", "test-secret")
    payload = {
        "event": "source_refresh_completed",
        "job_id": "job-duplicate",
        "metadata_novel_id": 78,
        "source_id": 9,
        "site": "royalroad",
        "new_chapter_numbers": [21],
        "chapters": [{"chapter_number": 21, "chapter_id": 21, "title": "Twenty-one"}],
    }
    first = client_with_auth.post("/novel/internal/metadata-events", headers={"X-Nexus-Webhook-Secret": "test-secret"}, json=payload)
    second = client_with_auth.post("/novel/internal/metadata-events", headers={"X-Nexus-Webhook-Secret": "test-secret"}, json=payload)

    assert first.json() == {"accepted": True, "created_events": 1, "queued_downloads": 1}
    assert second.json() == {"accepted": True, "created_events": 0, "queued_downloads": 0}
    assert db.query(MetadataWebhookDelivery).count() == 1
    assert db.query(NovelUpdateEvent).filter(NovelUpdateEvent.novel_id == novel.id).count() == 1
    assert db.query(ChapterDownloadJob).filter(ChapterDownloadJob.novel_id == novel.id).count() == 2


def test_metadata_refresh_event_ignores_unfollowed_novel(client_with_auth, db, monkeypatch):
    from app.models.download_job import ChapterDownloadJob
    from app.models.update_event import NovelUpdateEvent

    response, headers, _, url, library = add_novel_resources(client_with_auth, db)
    assert response.status_code == status.HTTP_201_CREATED
    novel = get_novel_by_url(db, url).first()
    novel.metadata_id = 79
    db.commit()
    monkeypatch.setenv("NEXUS_NOVEL_WEBHOOK_SECRET", "test-secret")

    response = client_with_auth.post(
        "/novel/internal/metadata-events",
        headers={"X-Nexus-Webhook-Secret": "test-secret"},
        json={
            "event": "source_refresh_completed",
            "job_id": "unfollowed-job",
            "metadata_novel_id": 79,
            "source_id": 9,
            "site": "royalroad",
            "new_chapter_numbers": [31],
        },
    )

    assert response.json() == {"accepted": True, "created_events": 0, "queued_downloads": 0}
    assert db.query(NovelUpdateEvent).filter(NovelUpdateEvent.novel_id == novel.id).count() == 0
    assert db.query(ChapterDownloadJob).filter(ChapterDownloadJob.novel_id == novel.id).count() == 0


def test_metadata_refresh_event_does_not_download_on_hold(client_with_auth, db, monkeypatch):
    from app.models.download_job import ChapterDownloadJob
    from app.models.update_event import NovelUpdateEvent

    response, headers, _, url, library = add_novel_resources(client_with_auth, db)
    assert response.status_code == status.HTTP_201_CREATED
    novel = get_novel_by_url(db, url).first()
    novel.metadata_id = 80
    db.commit()
    client_with_auth.patch(
        f"/novel/{novel.id}/follow?library_id={library.id}",
        json={"follow_state": "on_hold", "download_policy": "next_n", "download_count": 2},
        headers=headers,
    )
    existing_jobs = db.query(ChapterDownloadJob).filter(ChapterDownloadJob.novel_id == novel.id).count()
    monkeypatch.setenv("NEXUS_NOVEL_WEBHOOK_SECRET", "test-secret")

    response = client_with_auth.post(
        "/novel/internal/metadata-events",
        headers={"X-Nexus-Webhook-Secret": "test-secret"},
        json={
            "event": "source_refresh_completed",
            "job_id": "on-hold-job",
            "metadata_novel_id": 80,
            "source_id": 9,
            "site": "royalroad",
            "new_chapter_numbers": [41, 42],
        },
    )

    assert response.json() == {"accepted": True, "created_events": 0, "queued_downloads": 0}
    assert db.query(NovelUpdateEvent).filter(NovelUpdateEvent.novel_id == novel.id).count() == 0
    assert db.query(ChapterDownloadJob).filter(ChapterDownloadJob.novel_id == novel.id).count() == existing_jobs


def test_metadata_refresh_event_requires_secret_before_claiming(client_with_auth, db, monkeypatch):
    from app.models.metadata_webhook_delivery import MetadataWebhookDelivery

    monkeypatch.setenv("NEXUS_NOVEL_WEBHOOK_SECRET", "test-secret")
    response = client_with_auth.post(
        "/novel/internal/metadata-events",
        headers={"X-Nexus-Webhook-Secret": "wrong-secret"},
        json={
            "event": "source_refresh_completed",
            "job_id": "unauthorized-job",
            "metadata_novel_id": 999,
            "source_id": 9,
            "site": "royalroad",
        },
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert db.query(MetadataWebhookDelivery).count() == 0


def test_metadata_webhook_delivery_claim_is_unique_across_sessions(db):
    from app.models.metadata_webhook_delivery import MetadataWebhookDelivery
    from app.routers.novel import claim_metadata_webhook_delivery, MetadataRefreshEvent
    from sqlalchemy.orm import sessionmaker

    event = MetadataRefreshEvent(
        event="source_refresh_completed",
        job_id="concurrent-job",
        metadata_novel_id=999,
        source_id=12,
        site="royalroad",
    )
    session_factory = sessionmaker(bind=db.get_bind())
    first_session = session_factory()
    second_session = session_factory()
    try:
        assert claim_metadata_webhook_delivery(first_session, event) is True
        first_session.commit()
        assert claim_metadata_webhook_delivery(second_session, event) is False
        second_session.rollback()
    finally:
        first_session.close()
        second_session.close()

    assert db.query(MetadataWebhookDelivery).count() == 1


def test_metadata_webhook_allows_failure_then_success_for_same_source_job(db):
    from app.models.metadata_webhook_delivery import MetadataWebhookDelivery
    from app.routers.novel import MetadataRefreshEvent, claim_metadata_webhook_delivery

    failed = MetadataRefreshEvent(
        event="source_refresh_failed",
        job_id="retried-job",
        metadata_novel_id=999,
        source_id=12,
        site="royalroad",
    )
    completed = MetadataRefreshEvent(
        event="source_refresh_completed",
        job_id="retried-job",
        metadata_novel_id=999,
        source_id=12,
        site="royalroad",
    )

    assert claim_metadata_webhook_delivery(db, failed) is True
    db.commit()
    assert claim_metadata_webhook_delivery(db, completed) is True
    db.commit()

    assert db.query(MetadataWebhookDelivery).count() == 2


def test_update_events_are_user_scoped_and_markable(client_with_auth, db):
    response, headers, _, url, library = add_novel_resources(client_with_auth, db)
    assert response.status_code == status.HTTP_201_CREATED
    novel = get_novel_by_url(db, url).first()
    assert novel is not None

    from app.models.update_event import NovelUpdateEvent

    event = NovelUpdateEvent(
        user_id=library.user_id,
        novel_id=novel.id,
        event_type="new_chapters",
        chapter_count=2,
        first_chapter_number=11,
        last_chapter_number=12,
        message="2 new chapter(s) available",
        details={"chapter_numbers": [11, 12]},
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    response = client_with_auth.get(
        f"/novel/updates?library_id={library.id}&unread_only=true",
        headers=headers,
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()[0]["id"] == event.id

    response = client_with_auth.post(
        f"/novel/updates/{event.id}/read",
        headers=headers,
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["read_at"] is not None


def test_background_metadata_calls_run_on_the_owning_event_loop():
    """The pooled metadata client must never be used from a second loop."""
    import asyncio
    import threading

    from app.routers.novel import _run_metadata_call

    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()

    async def which_loop():
        return asyncio.get_running_loop()

    try:
        assert _run_metadata_call(which_loop(), loop) is loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=5)
        loop.close()
