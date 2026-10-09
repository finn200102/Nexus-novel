"""F1: follow authors and series; new-work webhook events become update events."""
from unittest.mock import AsyncMock, patch

from app.models.creator_follow import CreatorFollow
from app.models.library import Library
from app.models.novel import Novel
from app.models.update_event import NovelUpdateEvent
from app.models.user import User
from app.services.notification_delivery import build_messages
from tests.auth_helpers import bearer_headers

SECRET = {"X-Nexus-Webhook-Secret": "test-secret"}


def _target_response(kind="author", site="royalroad", key="100374", count=1, target_id=7):
    return {"id": target_id, "kind": kind, "site": site, "key": key, "name": "nobody103", "follower_count": count, "works": []}


def _event(delivery_id: str, *, kind="author", key="100374", metadata_id=55, title="Zenith of Sorcery"):
    return {
        "event": f"{kind}_new_work",
        "delivery_id": delivery_id,
        "job_id": "job-1",
        "metadata_novel_id": metadata_id,
        "source_id": 0,
        "site": "royalroad" if kind == "author" else "archive",
        "target": {"id": 7, "kind": kind, "site": "royalroad" if kind == "author" else "archive", "key": key, "name": "nobody103"},
        "work": {"metadata_id": metadata_id, "title": title, "url": f"https://www.royalroad.com/fiction/{metadata_id}", "author": "nobody103"},
    }


def _other_user(db) -> User:
    user = User(username="second-reader", password="hashed_password_here")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_follow_reports_follower_counts_and_unfollow(client_with_auth, db, test_user):
    headers = bearer_headers(test_user.id)
    with patch("app.services.creator_follow_service.metadata_client.put_follow_target", new_callable=AsyncMock) as put:
        put.return_value = _target_response()
        created = client_with_auth.post(
            "/following", headers=headers,
            json={"kind": "author", "site": "royalroad", "key": "100374", "name": "nobody103", "metadata_author_id": 1},
        )
        assert created.status_code == 201, created.text
        assert created.json()["metadata_target_id"] == 7
        put.assert_awaited_with("author", "royalroad", "100374", "nobody103", 1)

        again = client_with_auth.post("/following", headers=headers, json={"kind": "author", "site": "royalroad", "key": "100374"})
        assert again.json()["id"] == created.json()["id"]

        listed = client_with_auth.get("/following", headers=headers).json()
        assert [(row["kind"], row["key"]) for row in listed] == [("author", "100374")]

        put.return_value = _target_response(count=0)
        assert client_with_auth.delete(f"/following/{created.json()['id']}", headers=headers).status_code == 204
        put.assert_awaited_with("author", "royalroad", "100374", "nobody103", 0)
        assert client_with_auth.get("/following", headers=headers).json() == []


def test_unsupported_target_is_rejected_and_not_kept(client_with_auth, db, test_user):
    headers = bearer_headers(test_user.id)
    with patch("app.services.creator_follow_service.metadata_client.put_follow_target", new_callable=AsyncMock) as put:
        put.side_effect = RuntimeError("Metadata server returned HTTP 422: not supported")
        response = client_with_auth.post("/following", headers=headers, json={"kind": "series", "site": "fanfiction", "key": "1"})
    assert response.status_code == 422
    assert db.query(CreatorFollow).count() == 0


def test_new_work_event_reaches_followers_once(client_with_auth, db, test_user, monkeypatch):
    monkeypatch.setenv("NEXUS_NOVEL_WEBHOOK_SECRET", "test-secret")
    other = _other_user(db)
    stranger = User(username="not-following", password="hashed_password_here")
    db.add(stranger)
    db.add_all([
        CreatorFollow(user_id=test_user.id, kind="author", site="royalroad", target_key="100374", name="nobody103"),
        CreatorFollow(user_id=other.id, kind="author", site="royalroad", target_key="100374", name="nobody103"),
        # Following the series too must not double the update.
        CreatorFollow(user_id=test_user.id, kind="series", site="archive", target_key="9", name="Saga"),
    ])
    db.commit()

    first = client_with_auth.post("/novel/internal/metadata-events", headers=SECRET, json=_event("d-1"))
    assert first.json()["created_events"] == 2
    replay = client_with_auth.post("/novel/internal/metadata-events", headers=SECRET, json=_event("d-1"))
    assert replay.json()["created_events"] == 0
    same_work_via_series = client_with_auth.post(
        "/novel/internal/metadata-events", headers=SECRET, json=_event("d-2", kind="series", key="9"),
    )
    assert same_work_via_series.json()["created_events"] == 0

    events = db.query(NovelUpdateEvent).filter(NovelUpdateEvent.event_type == "author_new_work").all()
    assert sorted(event.user_id for event in events) == sorted([test_user.id, other.id])
    assert all(event.novel_id is None for event in events)
    assert events[0].details["title"] == "Zenith of Sorcery"

    inbox = client_with_auth.get("/following/new-works", headers=bearer_headers(test_user.id)).json()
    assert [(row["title"], row["metadata_id"]) for row in inbox] == [("Zenith of Sorcery", 55)]
    assert "nobody103" in inbox[0]["message"]

    marked = client_with_auth.post("/following/new-works/read", headers=bearer_headers(test_user.id))
    assert marked.json() == {"updated": 1}
    assert client_with_auth.get("/following/new-works", headers=bearer_headers(test_user.id)).json() == []

    messages = build_messages(db, events)
    assert messages[test_user.id][0].title == "Zenith of Sorcery"
    assert messages[test_user.id][0].url == "/story/55"


def test_work_already_in_a_library_is_not_announced(client_with_auth, db, test_user, monkeypatch):
    monkeypatch.setenv("NEXUS_NOVEL_WEBHOOK_SECRET", "test-secret")
    library = db.query(Library).filter(Library.user_id == test_user.id).first()
    db.add(Novel(title="Zenith", url="https://www.royalroad.com/fiction/55", library_id=library.id, novel_site="royalroad", metadata_id=55))
    db.add(CreatorFollow(user_id=test_user.id, kind="author", site="royalroad", target_key="100374"))
    db.commit()
    response = client_with_auth.post("/novel/internal/metadata-events", headers=SECRET, json=_event("d-9"))
    assert response.json()["created_events"] == 0


def test_author_page_marks_followed_profiles(client_with_auth, db, test_user):
    db.add(CreatorFollow(user_id=test_user.id, kind="author", site="royalroad", target_key="100374"))
    db.commit()
    data = {"id": 1, "name": "nobody103", "site": "royalroad", "profiles": [
        {"id": 1, "site": "royalroad", "key": "100374", "followable": True, "works": []},
        {"id": 2, "site": "archive", "key": "nobody103", "followable": True, "works": []},
    ]}
    with patch("app.routers.creator_follows.metadata_client.get_author_works", new_callable=AsyncMock) as works:
        works.return_value = data
        page = client_with_auth.get("/following/authors/1", headers=bearer_headers(test_user.id)).json()
    assert [profile["follow_id"] is not None for profile in page["profiles"]] == [True, False]
