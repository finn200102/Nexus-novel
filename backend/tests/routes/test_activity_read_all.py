
from app.models.update_event import NovelUpdateEvent
from tests.auth_helpers import bearer_headers


def test_read_all_marks_only_events_in_that_library(client, db, test_user, test_library):
    from app.models.library import Library
    from app.models.novel import Novel

    other = Library(name="Other", user_id=test_user.id)
    db.add(other)
    db.flush()
    inside = Novel(title="Inside", url="https://example.test/a", library_id=test_library.id)
    outside = Novel(title="Outside", url="https://example.test/b", library_id=other.id)
    db.add_all([inside, outside])
    db.flush()
    db.add_all([
        NovelUpdateEvent(user_id=test_user.id, novel_id=inside.id, event_type="new_chapters"),
        NovelUpdateEvent(user_id=test_user.id, novel_id=outside.id, event_type="new_chapters"),
    ])
    db.commit()

    response = client.post(f"/activity/read-all?library_id={test_library.id}", headers=bearer_headers(test_user.id))

    assert response.status_code == 200
    assert response.json() == {"updated": 1}
    unread = db.query(NovelUpdateEvent).filter(NovelUpdateEvent.read_at.is_(None)).all()
    assert [event.novel_id for event in unread] == [outside.id]
