from app.models.chapter import Chapter
from app.models.novel import Novel
from app.models.reading_progress import ReadingProgress
from tests.auth_helpers import bearer_headers


def _novel(db, library) -> Novel:
    novel = Novel(title="Serial", url="https://example.test/serial", library_id=library.id, novel_site="royalroad")
    db.add(novel)
    db.commit()
    db.refresh(novel)
    return novel


def _chapter(db, novel, number, category="story") -> Chapter:
    chapter = Chapter(novel_id=novel.id, chapter_number=number, title=f"Chapter {number}", category=category, site_chapter_id=100 + number)
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter


def _move_progress(db, user, novel, chapter):
    progress = db.query(ReadingProgress).filter(ReadingProgress.user_id == user.id, ReadingProgress.novel_id == novel.id).first()
    if progress is None:
        progress = ReadingProgress(user_id=user.id, novel_id=novel.id)
        db.add(progress)
    progress.chapter_id = chapter.id
    progress.chapter_number = chapter.chapter_number
    db.commit()


def test_novel_payloads_expose_next_unread_chapter(client, db, test_user, test_library):
    headers = bearer_headers(test_user.id)
    novel = _novel(db, test_library)
    first = _chapter(db, novel, 1)
    _chapter(db, novel, 2, category="side")
    third = _chapter(db, novel, 3)

    detail = client.get(f"/novel/{novel.id}?library_id={test_library.id}", headers=headers).json()
    assert detail["next_unread_chapter_id"] == first.id
    assert detail["next_unread_chapter_number"] == 1

    _move_progress(db, test_user, novel, first)
    listed = client.get(f"/novel/?library_id={test_library.id}", headers=headers).json()
    assert listed[0]["next_unread_chapter_id"] == third.id
    assert listed[0]["next_unread_chapter_number"] == 3

    _move_progress(db, test_user, novel, third)
    listed = client.get(f"/novel/?library_id={test_library.id}", headers=headers).json()
    assert listed[0]["next_unread_chapter_id"] is None
    assert listed[0]["next_unread_chapter_number"] is None


def test_personal_put_changes_only_the_fields_sent(client, db, test_user, test_library):
    headers = bearer_headers(test_user.id)
    novel = _novel(db, test_library)
    url = f"/personal/novels/{novel.id}"
    client.put(url, json={"notes": "keep me", "rating": 3, "user_tags": ["fav"], "auto_download": True}, headers=headers)

    # Toggling auto-download alone leaves notes, rating and tags alone.
    toggled = client.put(url, json={"auto_download": False, "keep_ahead": 12}, headers=headers).json()
    assert (toggled["notes"], toggled["rating"], toggled["user_tags"]) == ("keep me", 3, ["fav"])
    assert (toggled["auto_download"], toggled["keep_ahead"]) == (False, 12)

    # An explicit null clears notes and rating; the tags stay.
    cleared = client.put(url, json={"notes": None, "rating": None}, headers=headers).json()
    assert (cleared["notes"], cleared["rating"], cleared["user_tags"]) == (None, None, ["fav"])

    # Sending tags replaces them and leaves the rest alone.
    retagged = client.put(url, json={"user_tags": ["a", "b"]}, headers=headers).json()
    assert retagged["user_tags"] == ["a", "b"]
    assert retagged["keep_ahead"] == 12

    # An empty body changes nothing.
    unchanged = client.put(url, json={}, headers=headers).json()
    assert (unchanged["notes"], unchanged["user_tags"], unchanged["auto_download"], unchanged["keep_ahead"]) == (None, ["a", "b"], False, 12)


def test_personal_followed_categories_round_trip(client, db, test_user, test_library):
    headers = bearer_headers(test_user.id)
    novel = _novel(db, test_library)

    assert client.get(f"/personal/novels/{novel.id}", headers=headers).json()["followed_categories"] == ["story"]

    saved = client.put(f"/personal/novels/{novel.id}", json={"followed_categories": [" Story ", "side", "side"]}, headers=headers)
    assert saved.status_code == 200
    assert saved.json()["followed_categories"] == ["story", "side"]

    # Omitting the field keeps the stored categories.
    kept = client.put(f"/personal/novels/{novel.id}", json={"rating": 4}, headers=headers).json()
    assert kept["followed_categories"] == ["story", "side"]
    assert kept["rating"] == 4

    empty = client.put(f"/personal/novels/{novel.id}", json={"followed_categories": []}, headers=headers)
    assert empty.status_code == 422
