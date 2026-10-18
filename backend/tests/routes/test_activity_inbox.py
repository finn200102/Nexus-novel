from datetime import UTC, datetime, timedelta

from app.models.chapter import Chapter, ContentStatus
from app.models.download_job import ChapterDownloadJob
from app.models.follow import UserNovelFollow
from app.models.novel import Novel
from app.models.novel_personal import NovelPersonalData
from app.models.reading_progress import ReadingProgress
from app.models.update_event import NovelUpdateEvent
from tests.auth_helpers import bearer_headers


def _novel(db, library, title="Serial", metadata_id=None) -> Novel:
    novel = Novel(title=title, url=f"https://example.test/{title}", library_id=library.id, novel_site="royalroad", metadata_id=metadata_id)
    db.add(novel)
    db.commit()
    db.refresh(novel)
    return novel


def _chapter(db, novel, number, category="story", status=ContentStatus.MISSING) -> Chapter:
    chapter = Chapter(novel_id=novel.id, chapter_number=number, title=f"Chapter {number}", category=category, content_status=status, site_chapter_id=100 + number)
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter


def _event(db, user, novel, numbers, *, read=False, minutes_ago=0) -> NovelUpdateEvent:
    event = NovelUpdateEvent(
        user_id=user.id,
        novel_id=novel.id,
        event_type="new_chapters",
        chapter_count=len(numbers),
        first_chapter_number=min(numbers),
        last_chapter_number=max(numbers),
        message="new",
        details={"chapter_numbers": numbers},
        read_at=datetime.now(UTC) if read else None,
        notification_visible=True,
        created_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=minutes_ago),
    )
    db.add(event)
    db.commit()
    return event


def _personal(db, user, novel, **kwargs) -> NovelPersonalData:
    row = NovelPersonalData(user_id=user.id, novel_id=novel.id, **kwargs)
    db.add(row)
    db.commit()
    return row


def test_inbox_counts_only_followed_categories_and_sorts_newest_first(client, db, test_user, test_library):
    headers = bearer_headers(test_user.id)
    serial = _novel(db, test_library, "Serial")
    first = _chapter(db, serial, 1)
    _chapter(db, serial, 2, category="side")
    _chapter(db, serial, 3)
    _event(db, test_user, serial, [1, 2, 3], minutes_ago=30)
    only_side = _novel(db, test_library, "OnlySide")
    _chapter(db, only_side, 5, category="side")
    _event(db, test_user, only_side, [5], minutes_ago=5)
    newer = _novel(db, test_library, "Newer")
    _chapter(db, newer, 4)
    _event(db, test_user, newer, [4], minutes_ago=1)
    read_novel = _novel(db, test_library, "Read")
    _chapter(db, read_novel, 9)
    _event(db, test_user, read_novel, [9], read=True)

    rows = client.get(f"/activity/inbox?library_id={test_library.id}", headers=headers).json()

    assert [row["title"] for row in rows] == ["Newer", "Serial"]
    serial_row = rows[1]
    assert serial_row["new_chapter_count"] == 2
    assert serial_row["first_new_chapter_number"] == 1
    assert serial_row["next_unread_chapter_id"] == first.id
    assert serial_row["next_unread_chapter_number"] == 1
    assert len(serial_row["event_ids"]) == 1


def test_read_endpoint_marks_only_that_novel(client, db, test_user, test_library):
    headers = bearer_headers(test_user.id)
    a = _novel(db, test_library, "A")
    _chapter(db, a, 1)
    b = _novel(db, test_library, "B")
    _chapter(db, b, 1)
    _event(db, test_user, a, [1])
    event_b = _event(db, test_user, b, [1])

    response = client.post(f"/activity/inbox/{a.id}/read", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"updated": 1}
    rows = client.get(f"/activity/inbox?library_id={test_library.id}", headers=headers).json()
    assert [row["novel_id"] for row in rows] == [b.id]
    assert [row["event_ids"] for row in rows] == [[event_b.id]]


def test_caught_up_marks_read_and_moves_progress_to_latest_followed_chapter(client, db, test_user, test_library):
    headers = bearer_headers(test_user.id)
    serial = _novel(db, test_library)
    _chapter(db, serial, 1)
    _chapter(db, serial, 2, category="side")
    latest = _chapter(db, serial, 3)
    _chapter(db, serial, 4, category="side")
    _event(db, test_user, serial, [1, 2, 3, 4])

    response = client.post(f"/activity/inbox/{serial.id}/caught-up", headers=headers)

    assert response.status_code == 200
    assert response.json() == {"updated": 1, "progress_chapter_number": 3}
    progress = db.query(ReadingProgress).filter(ReadingProgress.user_id == test_user.id, ReadingProgress.novel_id == serial.id).one()
    assert progress.chapter_id == latest.id
    assert progress.percent == 100
    assert client.get(f"/activity/inbox?library_id={test_library.id}", headers=headers).json() == []


def test_caught_up_never_moves_progress_backwards(client, db, test_user, test_library):
    headers = bearer_headers(test_user.id)
    serial = _novel(db, test_library)
    _chapter(db, serial, 1)
    far = _chapter(db, serial, 5)
    _event(db, test_user, serial, [1])
    db.add(ReadingProgress(user_id=test_user.id, novel_id=serial.id, chapter_id=far.id, chapter_number=5, position=0, percent=20))
    db.commit()

    response = client.post(f"/activity/inbox/{serial.id}/caught-up", headers=headers)

    assert response.json() == {"updated": 1, "progress_chapter_number": None}
    progress = db.query(ReadingProgress).filter(ReadingProgress.user_id == test_user.id, ReadingProgress.novel_id == serial.id).one()
    assert progress.chapter_id == far.id


def test_inbox_endpoints_reject_other_users_novels(client, db, test_user, test_library):
    serial = _novel(db, test_library)
    _chapter(db, serial, 1)
    _event(db, test_user, serial, [1])
    from app.models.user import User

    stranger = User(username="stranger", password="hashed_password_here")
    db.add(stranger)
    db.commit()
    other_user_headers = bearer_headers(stranger.id)

    assert client.post(f"/activity/inbox/{serial.id}/read", headers=other_user_headers).status_code == 404
    assert client.post(f"/activity/inbox/{serial.id}/caught-up", headers=other_user_headers).status_code == 404


def test_auto_download_is_off_by_default(db, test_user, test_library):
    from app.services.auto_download_service import queue_auto_downloads

    serial = _novel(db, test_library)
    for number in range(1, 4):
        _chapter(db, serial, number)

    assert queue_auto_downloads(db, user_id=test_user.id, library_id=test_library.id, novel=serial) == 0
    assert db.query(ChapterDownloadJob).count() == 0


def test_auto_download_queues_keep_ahead_after_position_and_skips_downloaded(db, test_user, test_library):
    from app.services.auto_download_service import queue_auto_downloads

    serial = _novel(db, test_library)
    chapters = [_chapter(db, serial, number) for number in range(1, 9)]
    chapters[3].content_status = ContentStatus.PRESENT  # chapter 4 already downloaded
    db.commit()
    _personal(db, test_user, serial, auto_download=True, keep_ahead=3)
    db.add(ReadingProgress(user_id=test_user.id, novel_id=serial.id, chapter_id=chapters[1].id, chapter_number=2, position=0, percent=50))
    db.commit()

    # Window after chapter 2 is 3, 5, 6: chapter 4 is skipped because it is downloaded.
    assert queue_auto_downloads(db, user_id=test_user.id, library_id=test_library.id, novel=serial) == 3
    db.commit()
    queued = {job.chapter_id for job in db.query(ChapterDownloadJob).all()}
    assert queued == {chapters[2].id, chapters[4].id, chapters[5].id}


def test_auto_download_dedupes_against_active_jobs(db, test_user, test_library):
    from app.services.auto_download_service import queue_auto_downloads

    serial = _novel(db, test_library)
    chapters = [_chapter(db, serial, number) for number in range(1, 6)]
    _personal(db, test_user, serial, auto_download=True, keep_ahead=3)
    db.add(ChapterDownloadJob(user_id=test_user.id, library_id=test_library.id, novel_id=serial.id, chapter_id=chapters[0].id, status="processing"))
    db.commit()

    assert queue_auto_downloads(db, user_id=test_user.id, library_id=test_library.id, novel=serial) == 2
    assert queue_auto_downloads(db, user_id=test_user.id, library_id=test_library.id, novel=serial) == 0
    assert db.query(ChapterDownloadJob).count() == 3


def test_auto_download_per_run_cap_is_50(db, test_user, test_library):
    from app.services.auto_download_service import queue_auto_downloads

    serial = _novel(db, test_library)
    for number in range(1, 71):
        _chapter(db, serial, number)
    _personal(db, test_user, serial, auto_download=True, keep_ahead=200)

    assert queue_auto_downloads(db, user_id=test_user.id, library_id=test_library.id, novel=serial) == 50


def test_metadata_webhook_auto_download_queues_window(client, db, test_user, test_library, monkeypatch):
    serial = _novel(db, test_library, metadata_id=77)
    for number in range(1, 4):
        _chapter(db, serial, number, status=ContentStatus.PRESENT)
    db.add(UserNovelFollow(user_id=test_user.id, novel_id=serial.id, state="reading"))
    _personal(db, test_user, serial, auto_download=True, keep_ahead=2)
    monkeypatch.setenv("NEXUS_NOVEL_WEBHOOK_SECRET", "test-secret")

    from tests.routes.metadata_event_fixture import peer
    snapshot,proof=peer(db,serial,monkeypatch,[
        {'chapter_number':4,'chapter_id':104,'title':'Four','category':'story'},
        {'chapter_number':5,'chapter_id':105,'title':'Five','category':'side'},
        {'chapter_number':6,'chapter_id':106,'title':'Six','category':'story'},
    ])
    response = client.post(
        "/novel/internal/metadata-events",
        headers={"X-Nexus-Webhook-Secret": "test-secret"},
        json={
            "event": "source_refresh_completed",
            "job_id": "job-auto",
            "metadata_novel_id": 77,
            "source_id": 9,
            "site": "royalroad",
            "new_chapter_numbers": [4, 5, 6],
            "manifest_proof":proof,
            "chapters": [
                {"chapter_number": 4, "chapter_id": 4, "title": "Four", "category": "story"},
                {"chapter_number": 5, "chapter_id": 5, "title": "Five", "category": "side"},
                {"chapter_number": 6, "chapter_id": 6, "title": "Six", "category": "story"},
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["queued_downloads"] == 2
    queued = sorted(job.chapter.chapter_number for job in db.query(ChapterDownloadJob).all())
    assert queued == [4, 6]
    assert all(job.chapter_identity["metadata_manifest_key"]==snapshot.manifest_key for job in db.query(ChapterDownloadJob))


def test_personal_auto_download_settings_round_trip(client, db, test_user, test_library):
    headers = bearer_headers(test_user.id)
    serial = _novel(db, test_library)
    url = f"/personal/novels/{serial.id}"

    assert client.get(url, headers=headers).json()["auto_download"] is False
    assert client.get(url, headers=headers).json()["keep_ahead"] == 10
    response = client.put(url, json={"auto_download": True, "keep_ahead": 25}, headers=headers)
    assert response.json()["auto_download"] is True
    assert response.json()["keep_ahead"] == 25
    # A save that omits the settings keeps them.
    response = client.put(url, json={"notes": "hi"}, headers=headers)
    assert response.json()["auto_download"] is True
    assert response.json()["keep_ahead"] == 25
    assert client.put(url, json={"keep_ahead": 500}, headers=headers).status_code == 422


def test_novel_detail_keeps_existing_chapters_readable_when_source_changes_need_review(client, db, test_user, test_library, monkeypatch):
    from app.services import metadata_client
    from uuid import uuid4

    headers = bearer_headers(test_user.id)
    serial = _novel(db, test_library, metadata_id=7)
    _chapter(db, serial, 1)
    second = _chapter(db, serial, 2, category="side")

    async def fake_metadata(metadata_id):
        return {"title": "Serial"}

    async def fake_manifest(metadata_id):
        return metadata_client.ChapterManifestSnapshot(novel_id=metadata_id, manifest_key=str(uuid4()),
            revision='1', fingerprint='a' * 64, identity_kind='stable_source_id', total=2,
            source={'site': 'royalroad', 'story_id': 77, 'source_url': serial.url}, items=[
                {'id': number, 'chapter_key': str(uuid4()), 'chapter_number': number, 'chapter_id': 100 + number,
                 'category': 'story', 'identity_kind': 'stable_source_id', 'title': f'Chapter {number}',
                 'url': f'https://synthetic.invalid/{number}', 'word_count': 100}
                for number in (1, 2)])

    monkeypatch.setattr(metadata_client, "get_novel_metadata", fake_metadata)
    monkeypatch.setattr(metadata_client, "get_chapter_manifest", fake_manifest)

    response = client.get(f"/novel/{serial.id}?library_id={test_library.id}", headers=headers)
    assert response.status_code == 200
    assert response.json()['chapter_manifest_review_required'] is True
    db.refresh(second)
    assert second.category == "side"
    assert db.query(Chapter).filter_by(novel_id=serial.id).count() == 2


def test_metadata_webhook_category_drift_preserves_original_for_review(client, db, test_user, test_library, monkeypatch):
    serial = _novel(db, test_library, metadata_id=78)
    existing = _chapter(db, serial, 1, category="side")
    existing.content="Preserved downloaded side chapter."
    existing.content_status=ContentStatus.PRESENT
    db.add(UserNovelFollow(user_id=test_user.id, novel_id=serial.id, state="reading"))
    db.commit()
    monkeypatch.setenv("NEXUS_NOVEL_WEBHOOK_SECRET", "test-secret")

    from tests.routes.metadata_event_fixture import peer
    snapshot,proof=peer(db,serial,monkeypatch,[{'chapter_number':1,'chapter_id':101,'title':'One','category':'story'}])
    response = client.post(
        "/novel/internal/metadata-events",
        headers={"X-Nexus-Webhook-Secret": "test-secret"},
        json={
            "event": "source_refresh_completed",
            "job_id": "job-cat",
            "metadata_novel_id": 78,
            "source_id": 9,
            "site": "royalroad",
            "new_chapter_numbers": [1],
            "manifest_proof":proof,
            "chapters": [{"chapter_number": 1, "chapter_id": 1, "title": "One", "category": "story"}],
        },
    )

    assert response.status_code == 200
    db.refresh(existing)
    assert existing.category == "side" and existing.content=="Preserved downloaded side chapter."
    assert existing.content_status==ContentStatus.PRESENT
    assert response.json()['state']=='review_required'
    assert db.query(ChapterDownloadJob).count()==0
    review=db.query(NovelUpdateEvent).one()
    assert review.event_type=='source_manifest_review_required' and review.details['code']=='chapter_review_required'
    duplicate=client.post('/novel/internal/metadata-events',headers={'X-Nexus-Webhook-Secret':'test-secret'},json={
        'event':'source_refresh_completed','job_id':'job-cat','metadata_novel_id':78,'source_id':9,'site':'royalroad','manifest_proof':proof})
    assert duplicate.status_code==200 and duplicate.json()['state']=='duplicate'
    assert db.query(NovelUpdateEvent).count()==1


def test_inbox_count_endpoint_and_operations_match_inbox_rows(client, db, test_user, test_library):
    headers = bearer_headers(test_user.id)
    first = _novel(db, test_library, "First")
    _chapter(db, first, 1)
    _event(db, test_user, first, [1], minutes_ago=2)
    second = _novel(db, test_library, "Second")
    _chapter(db, second, 3)
    _event(db, test_user, second, [3], minutes_ago=1)
    _event(db, test_user, second, [3], minutes_ago=0)
    read = _novel(db, test_library, "Read")
    _chapter(db, read, 4)
    _event(db, test_user, read, [4], read=True)

    rows = client.get(f"/activity/inbox?library_id={test_library.id}", headers=headers).json()
    count = client.get(f"/activity/inbox/count?library_id={test_library.id}", headers=headers).json()
    summary = client.get(f"/operations/summary?library_id={test_library.id}", headers=headers).json()

    assert len(rows) == 2
    assert count == {"count": 2}
    assert summary["unread_updates"] == 2


def test_unread_story_count_includes_new_work_events_once_per_work(db, test_user, test_library):
    from app.services.activity_service import unread_story_count

    def new_work(work_key, *, read=False):
        db.add(NovelUpdateEvent(
            user_id=test_user.id,
            novel_id=None,
            event_type="author_new_work",
            message="New work",
            details={"work_key": work_key, "title": work_key, "url": f"https://example.test/{work_key}"},
            notification_visible=True,
            read_at=datetime.now(UTC) if read else None,
        ))

    new_work("royalroad:1")
    new_work("royalroad:1")
    new_work("sufficientvelocity:2")
    new_work("royalroad:3", read=True)
    db.commit()
    assert unread_story_count(db, user_id=test_user.id, library_id=test_library.id) == 2
