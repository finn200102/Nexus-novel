from app.models.chapter import Chapter
from app.models.novel import Novel
from app.models.reading_history import ReadingHistory
from app.models.reading_progress import ReadingProgress



def test_progress_replay_conflict_and_rewind(client, db, test_user, test_library, auth_headers):
    novel = Novel(title="Progress", library_id=test_library.id)
    db.add(novel)
    db.flush()
    db.add_all([Chapter(novel_id=novel.id, chapter_number=n, title=str(n)) for n in (1, 2)])
    db.commit()
    url = f"/chapter/progress/{novel.id}"
    headers = auth_headers
    first = {"chapter_number": 2, "percent": 75, "expected_revision": 0, "operation_id": "first"}
    saved = client.put(url, json=first, headers=headers)
    assert saved.status_code == 200
    assert saved.json()["revision"] == 1
    assert client.put(url, json=first, headers=headers).json() == saved.json()
    assert db.query(ReadingHistory).count() == 1
    stale = client.put(url, json={**first, "chapter_number": 1, "operation_id": "stale"}, headers=headers)
    assert stale.status_code == 409
    assert stale.json()["detail"]["current"]["revision"] == 1
    rewind = client.put(url, json={"chapter_number": 1, "percent": 10, "expected_revision": 1,
                                  "operation_id": "rewind", "intent": "rewind"}, headers=headers)
    assert rewind.status_code == 200
    assert rewind.json()["chapter_number"] == 1
    assert rewind.json()["furthest_chapter_number"] == 2
    assert rewind.json()["furthest_percent"] == 75
    assert db.query(ReadingProgress).one().revision == 2
    reused = client.put(url, json={**first, "percent": 50}, headers=headers)
    assert reused.status_code == 409
