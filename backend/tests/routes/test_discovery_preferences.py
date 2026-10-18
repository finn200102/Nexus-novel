from unittest.mock import AsyncMock
from app.models import User
from tests.auth_helpers import bearer_headers


def save(client, headers, **values):
    return client.put("/recommendations/preferences", headers=headers, json={"expected_revision": 0, "operation_id": "taste-setup", "values": values})


def test_private_revisioned_preferences_replay_and_portability(client, db, test_user, auth_headers):
    result = save(client, auth_headers, tags=["Slow burn", "slow burn"], exclude_tags=["Horror"])
    assert result.status_code == 200 and result.json()["values"]["tags"] == ["Slow burn"]
    assert save(client, auth_headers, tags=["Slow burn", "slow burn"], exclude_tags=["Horror"]).json() == result.json()
    stale = client.put("/recommendations/preferences", headers=auth_headers, json={"expected_revision": 0, "operation_id": "stale", "values": {"tags": ["Adventure"]}})
    assert stale.status_code == 409 and stale.json()["detail"]["current"]["revision"] == 1
    other = User(username="other-taste", password="unused")
    db.add(other); db.commit()
    assert client.get("/recommendations/preferences", headers=bearer_headers(other.id, db)).json()["revision"] == 0
    assert client.get("/me/export", headers=auth_headers).json()["discovery_preferences"]["exclude_tags"] == ["Horror"]
    assert save(client, auth_headers, tags=["X" * 101]).status_code == 422


def test_cold_start_uses_real_records_and_final_exclusions(client, auth_headers, monkeypatch):
    from app.services import metadata_client
    save(client, auth_headers, tags=["Slow burn"], languages=["en"], exclude_tags=["Horror"])
    listing = AsyncMock(return_value={"data": [
        {"id": 1, "title": "Matching story", "tags": ["Slow burn"], "language": "en"},
        {"id": 2, "title": "Excluded story", "tags": ["Horror"], "language": "en"},
        {"id": 3, "title": "Wrong language", "tags": ["Slow burn"], "language": "de"}]})
    monkeypatch.setattr(metadata_client, "list_novels_metadata", listing)
    response = client.get("/recommendations", headers=auth_headers)
    assert response.status_code == 200
    result = response.json()
    assert result["basis"] == "your_preferences" and [row["id"] for row in result["data"]] == [1]
    assert result["data"][0]["reasons"] == ["Matches your tag: Slow burn"]
    assert listing.await_args.kwargs["tag"] == ["Slow burn"]
    assert listing.await_args.kwargs["exclude_tag"] == ["Horror"]


def test_catalog_feed_is_labeled_and_unavailable_queries_return_partial_state(client, auth_headers, monkeypatch):
    from app.services import metadata_client
    monkeypatch.setattr(metadata_client, "list_novels_metadata", AsyncMock(return_value={"data": [{"id": 11, "title": "Actual feed work"}]}))
    assert client.get("/recommendations", headers=auth_headers).json()["basis"] == "catalog_feed"
    monkeypatch.setattr(metadata_client, "list_novels_metadata", AsyncMock(side_effect=RuntimeError("offline")))
    result = client.get("/recommendations", headers=auth_headers).json()
    assert result["data"] == [] and result["source_states"][0]["state"] == "unavailable"


def test_followed_story_tags_are_complete_filters_not_individual_characters(client, db, test_user, test_library, auth_headers, monkeypatch):
    from app.models import Novel, UserNovelFollow
    from app.services import metadata_client
    novel = Novel(library_id=test_library.id, title="Favorite", url="https://example.org/favorite", metadata_id=100)
    db.add(novel); db.flush()
    db.add(UserNovelFollow(user_id=test_user.id, novel_id=novel.id, state="reading")); db.commit()
    monkeypatch.setattr(metadata_client, "get_novel_metadata", AsyncMock(return_value={"tags": ["Slow burn"], "author": "Favorite author"}))
    listing = AsyncMock(return_value={"data": [{"id": 101, "title": "Actual similar story", "tags": ["Slow burn"], "author": "Another author"}]})
    monkeypatch.setattr(metadata_client, "list_novels_metadata", listing)
    result = client.get("/recommendations", headers=auth_headers).json()
    assert result["basis"] == "your_library" and result["data"][0]["id"] == 101
    assert listing.await_args.kwargs["tag"] == ["Slow burn"]
