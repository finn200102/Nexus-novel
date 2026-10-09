from unittest.mock import AsyncMock, patch

import pytest

from app.models.library import Library
from app.models.novel import Novel
from app.models.user import User
from tests.auth_helpers import bearer_headers


@pytest.fixture(autouse=True)
def no_metadata_hiatus():
    """Keep story tests off the metadata service; individual tests can override."""
    with patch(
        "app.routers.stories.metadata_client.get_hiatus_status",
        AsyncMock(side_effect=RuntimeError("metadata offline")),
    ):
        yield


def _user(db, name: str) -> User:
    user = User(username=name, password="hashed_password_here")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _copy(db, user: User, library_name: str, metadata_id: int | None, title: str = "Ledger") -> Novel:
    library = db.query(Library).filter_by(user_id=user.id, name=library_name).first()
    if library is None:
        library = Library(name=library_name, user_id=user.id)
        db.add(library)
        db.commit()
    novel = Novel(
        title=title,
        url=f"https://example.test/{library_name}/{metadata_id}/{title}",
        library_id=library.id,
        metadata_id=metadata_id,
        follow_state="reading",
    )
    db.add(novel)
    db.commit()
    db.refresh(novel)
    return novel


def test_story_lists_every_copy_of_the_current_user(client, db):
    me = _user(db, "reader")
    main = _copy(db, me, "Main", 42)
    archive = _copy(db, me, "Archive", 42)
    _copy(db, me, "Main", 7, title="Other")

    response = client.get("/stories/42", headers=bearer_headers(me.id))

    assert response.status_code == 200
    body = response.json()
    assert body["metadata_id"] == 42
    assert [(e["novel_id"], e["library_name"]) for e in body["library_entries"]] == [
        (archive.id, "Archive"),
        (main.id, "Main"),
    ]
    assert body["library_entries"][0]["follow_state"] == "reading"
    assert body["library_entries"][0]["library_id"] == archive.library_id


def test_story_never_shows_other_users_copies(client, db):
    me = _user(db, "reader")
    other = _user(db, "someone")
    _copy(db, other, "Theirs", 42)

    response = client.get("/stories/42", headers=bearer_headers(me.id))

    assert response.status_code == 200
    body = response.json()
    assert body["metadata_id"] == 42
    assert body["library_entries"] == []


def test_story_requires_sign_in(client):
    assert client.get("/stories/42").status_code == 401


def test_story_reports_hiatus_from_metadata(client, db):
    me = _user(db, "reader")
    mock = AsyncMock(return_value={"state": "likely_hiatus", "baseline_days": 2.0, "last_update_at": "2020-01-01T00:00:00+00:00"})
    with patch("app.routers.stories.metadata_client.get_hiatus_status", mock):
        response = client.get("/stories/42", headers=bearer_headers(me.id))

    assert response.status_code == 200
    assert response.json()["hiatus"]["state"] == "hiatus"
    assert response.json()["hiatus"]["last_update_at"] == "2020-01-01T00:00:00+00:00"
    mock.assert_awaited_once_with(42)


def test_story_hiatus_degrades_when_metadata_is_down(client, db):
    me = _user(db, "reader")
    response = client.get("/stories/42", headers=bearer_headers(me.id))

    assert response.status_code == 200
    assert response.json()["hiatus"] == {"state": "active", "last_update_at": None, "label": "Update timing unknown"}
