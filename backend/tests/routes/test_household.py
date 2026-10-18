"""Household instances: shared shelves (references, never content) and content-limited profiles."""
import asyncio
from unittest.mock import AsyncMock, patch

from app.models.audio_job import ChapterAudioJob
from app.models.chapter import Chapter, ContentStatus
from app.models.library import Library
from app.models.novel import Novel
from app.models.novel_personal import NovelPersonalData
from app.models.shelf import Shelf, ShelfNovel
from app.models.user import User
from app.services import content_limit_service
from app.services import import_job_service as imports
from tests.auth_helpers import bearer_headers
from tests.routes.conftest import TestingSessionLocal
from tests.routes.test_imports import FakeScrape, _metadata_scrape

CATALOG = {
    1: {"id": 1, "title": "Gentle", "content_rating": "general", "tags": ["Cozy"]},
    2: {"id": 2, "title": "Grim", "content_rating": "explicit", "tags": ["Gore"]},
    3: {"id": 3, "title": "Teen drama", "content_rating": "teen", "tags": ["Gore"]},
    4: {"id": 4, "title": "Mystery", "content_rating": "not_rated", "tags": []},
    1001: {"id": 1001, "title": "Imported gentle", "content_rating": "general"},
    1002: {"id": 1002, "title": "Imported grim", "content_rating": "mature"},
}


async def _metadata(novel_id):
    return dict(CATALOG[int(novel_id)])


def _patch_metadata():
    return patch("app.services.metadata_client.get_novel_metadata", AsyncMock(side_effect=_metadata))


def _user(db, name: str, **extra) -> User:
    user = User(username=name, password="hashed_password_here", **extra)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _library(db, user: User) -> Library:
    library = Library(name=f"{user.username} shelf", user_id=user.id)
    db.add(library)
    db.commit()
    db.refresh(library)
    return library


def _novel(db, library: Library, metadata_id: int) -> Novel:
    novel = Novel(title=CATALOG[metadata_id]["title"], url=f"https://www.royalroad.com/fiction/{metadata_id}",
                  library_id=library.id, novel_site="royalroad", metadata_id=metadata_id,
                  img_url=f"https://covers.example/{metadata_id}.jpg", scrape_status="completed")
    db.add(novel)
    db.commit()
    db.refresh(novel)
    return novel


def _household(db):
    owner, kid = _user(db, "parent"), _user(db, "kid")
    owner_lib = _library(db, owner)
    gentle, grim = _novel(db, owner_lib, 1), _novel(db, owner_lib, 2)
    shelf = Shelf(user_id=owner.id, name="Family picks")
    db.add(shelf)
    db.commit()
    for position, novel in enumerate((gentle, grim)):
        db.add(ShelfNovel(shelf_id=shelf.id, novel_id=novel.id, position=position))
    db.add(NovelPersonalData(user_id=owner.id, novel_id=gentle.id, notes="Read this one together"))
    chapter = Chapter(novel_id=gentle.id, chapter_number=1, title="One", content="Secret downloaded text", content_status=ContentStatus.PRESENT)
    db.add(chapter)
    db.commit()
    return owner, kid, shelf, gentle, grim, chapter


# ---------------------------------------------------------------- shared shelves


def test_owner_shares_shelf_and_recipient_sees_references_only(client, db):
    owner, kid, shelf, gentle, _grim, _chapter = _household(db)
    owner_h, kid_h = bearer_headers(owner.id), bearer_headers(kid.id)

    assert client.get(f"/shelves/{shelf.id}/stories", headers=kid_h).status_code == 404
    targets = client.get("/shelves/share-targets", headers=owner_h).json()
    assert targets == [{"id": kid.id, "username": "kid"}]
    shared = client.put(f"/shelves/{shelf.id}/shares/{kid.id}", json={"permission": "view"}, headers=owner_h)
    assert shared.json()["shares"] == [{"user_id": kid.id, "username": "kid", "permission": "view"}]
    assert client.get("/shelves", headers=owner_h).json()[0]["share_count"] == 1

    mine = client.get("/shelves/shared", headers=kid_h).json()
    assert [(row["name"], row["owner"]["username"], row["story_count"]) for row in mine] == [("Family picks", "parent", 2)]
    stories = client.get(f"/shelves/{shelf.id}/stories", headers=kid_h).json()["stories"]
    assert [row["metadata_id"] for row in stories] == [1, 2]
    first = stories[0]
    assert first["source_url"] == gentle.url and first["cover_url"].startswith("https://covers.example/")
    assert first["notes"] is None  # owner has not opted in
    for leaked in ("novel_id", "library_id", "content", "file_path", "cover_image"):
        assert all(leaked not in row for row in stories)

    client.patch(f"/shelves/{shelf.id}", json={"share_notes": True}, headers=owner_h)
    stories = client.get(f"/shelves/{shelf.id}/stories", headers=kid_h).json()["stories"]
    assert stories[0]["notes"] == "Read this one together"


def test_recipient_cannot_read_owner_content_via_any_endpoint(client, db, tmp_path):
    owner, kid, shelf, gentle, _grim, chapter = _household(db)
    owner_lib = gentle.library_id
    audio = tmp_path / "chapter.wav"
    audio.write_bytes(b"RIFF")
    job = ChapterAudioJob(user_id=owner.id, library_id=owner_lib, novel_id=gentle.id, chapter_id=chapter.id, status="completed",
                          provider_id="p", provider_url="http://tts", provider_model="m", provider_voice="v", audio_path=str(audio))
    db.add(job)
    db.commit()
    client.put(f"/shelves/{shelf.id}/shares/{kid.id}", json={"permission": "collaborate"}, headers=bearer_headers(owner.id))
    kid_h = bearer_headers(kid.id)
    _library(db, kid)

    attempts = [
        f"/chapter/content/library/{owner_lib}/{gentle.id}/1",
        f"/chapter/{gentle.id}/1",
        f"/chapter/{gentle.id}",
        f"/chapter/novel/{gentle.id}/export.epub",
        f"/novel/{gentle.id}?library_id={owner_lib}",
        f"/audio/jobs/{job.id}",
        f"/audio/jobs/{job.id}/audio",
    ]
    for url in attempts:
        response = client.get(url, headers=kid_h)
        assert response.status_code in (403, 404), url
        assert b"Secret downloaded text" not in response.content and response.content[:4] != b"RIFF", url
    # The owner still can.
    assert client.get(f"/chapter/content/library/{owner_lib}/{gentle.id}/1", headers=bearer_headers(owner.id)).status_code == 200
    # A collaborator cannot put someone else's copy on the shelf either.
    assert client.put(f"/shelves/{shelf.id}/entries/{gentle.id}", headers=kid_h).status_code == 404


def test_view_only_collaborate_and_leave(client, db):
    owner, kid, shelf, *_ = _household(db)
    owner_h, kid_h = bearer_headers(owner.id), bearer_headers(kid.id)
    kid_novel = _novel(db, _library(db, kid), 3)

    client.put(f"/shelves/{shelf.id}/shares/{kid.id}", json={"permission": "view"}, headers=owner_h)
    assert client.put(f"/shelves/{shelf.id}/entries/{kid_novel.id}", headers=kid_h).status_code == 403
    assert client.patch(f"/shelves/{shelf.id}", json={"name": "Mine now"}, headers=kid_h).status_code == 404
    assert client.get(f"/shelves/{shelf.id}/shares", headers=kid_h).status_code == 404

    client.put(f"/shelves/{shelf.id}/shares/{kid.id}", json={"permission": "collaborate"}, headers=owner_h)
    added = client.put(f"/shelves/{shelf.id}/entries/{kid_novel.id}", headers=kid_h).json()["stories"]
    entry = next(row for row in added if row["metadata_id"] == 3)
    assert entry["added_by"] == "kid" and entry["added_by_me"] and entry["in_my_library"]
    owner_entry = next(row for row in added if row["metadata_id"] == 1)
    assert client.delete(f"/shelves/{shelf.id}/entries/{owner_entry['entry_id']}", headers=kid_h).status_code == 403
    assert client.delete(f"/shelves/{shelf.id}/entries/{entry['entry_id']}", headers=kid_h).status_code == 200

    assert client.delete(f"/shelves/{shelf.id}/shares/{kid.id}", headers=kid_h).status_code == 200
    assert client.get("/shelves/shared", headers=kid_h).json() == []


# ---------------------------------------------------------------- content limits


def _limit(client, db, user: User, **limits):
    admin = _user(db, "admin", is_admin=True)
    response = client.put(f"/admin/users/{user.id}/content-limits", json=limits, headers=bearer_headers(admin.id))
    assert response.status_code == 200, response.text
    return response.json()


def test_admin_sets_limits_and_profile_sees_indicator(client, db):
    kid = _user(db, "kid")
    assert client.put(f"/admin/users/{kid.id}/content-limits", json={}, headers=bearer_headers(kid.id)).status_code == 403
    body = _limit(client, db, kid, max_content_rating="teen", blocked_tags=[" gore ", "Gore"])
    assert body["content_limits"] == {"max_content_rating": "teen", "hide_unrated": True, "blocked_tags": ["gore"], "limited": True}
    me = client.get("/auth/me", headers=bearer_headers(kid.id)).json()
    assert me["content_limits"]["limited"] is True
    assert client.put(f"/admin/users/{kid.id}/content-limits", json={"max_content_rating": "adult"},
                      headers=bearer_headers(_user(db, "admin2", is_admin=True).id)).status_code == 422


def test_rating_rules():
    user = User(username="x", max_content_rating="teen", hide_unrated=True, blocked_tags=["Gore"])
    assert content_limit_service.allowed_ratings(user) == ["general", "teen"]
    assert content_limit_service.item_allowed(user, CATALOG[1])
    assert not content_limit_service.item_allowed(user, CATALOG[2])
    assert not content_limit_service.item_allowed(user, CATALOG[3])  # blocked tag
    assert not content_limit_service.item_allowed(user, CATALOG[4])  # unrated hidden
    user.hide_unrated = False
    assert content_limit_service.item_allowed(user, CATALOG[4])
    assert content_limit_service.allowed_ratings(user)[-1] == "not_rated"
    assert content_limit_service.allowed_ratings(User(username="free")) is None


def test_discovery_catalog_filters_server_side_and_rows(client, db):
    kid = _user(db, "kid")
    _limit(client, db, kid, max_content_rating="teen")
    page = {"data": [CATALOG[1], CATALOG[2], CATALOG[4]], "next_cursor": None, "has_more": False}
    with patch("app.services.metadata_client.list_novels_metadata", AsyncMock(return_value=page)) as listing:
        rows = client.get("/discovery/novels/", headers=bearer_headers(kid.id)).json()["data"]
    assert [row["id"] for row in rows] == [1]
    assert listing.call_args.kwargs["content_rating"] == ["general", "teen"]


def test_live_search_drops_limited_results(client, db):
    kid = _user(db, "kid")
    _limit(client, db, kid, max_content_rating="mature", hide_unrated=False)
    answer = {"results": [
        {"metadata_id": 2, "url": "https://x/2", "title": "Grim", "content_rating": "explicit"},
        {"metadata_id": 4, "url": "https://x/4", "title": "Mystery"},
    ]}
    capability = {"source_id": "royalroad", "site": "royalroad", "name": "Royal Road",
                  "kind": "builtin", "search": True, "browse_feeds": ["best-rated"],
                  "user_lists": [], "plugin_id": None, "version": None,
                  "digest": None, "limitations": []}
    capabilities = {"search": ["royalroad"], "browse": {"royalroad": ["best-rated"]},
                    "user_lists": {}, "sources": [capability], "sources_limited": False}
    with patch("app.services.metadata_client.live_listing", AsyncMock(return_value=answer)), \
            patch("app.services.metadata_client.live_capabilities", AsyncMock(return_value=capabilities)), \
            patch("app.services.metadata_client._request", AsyncMock(side_effect=AssertionError("Household unit tests cannot contact a service"))):
        response = client.get("/discovery/live?q=x&include_local=false&sites=royalroad", headers=bearer_headers(kid.id))
        assert response.status_code == 200, response.text
        results = response.json()["results"]
        response = client.get("/discovery/live/browse?site=royalroad&feed=best-rated", headers=bearer_headers(kid.id))
        assert response.status_code == 200, response.text
        browse = response.json()["results"]
    assert [row["title"] for row in results] == ["Mystery"]
    assert [row["title"] for row in browse] == ["Mystery"]


def test_similar_and_story_page_are_limited(client, db):
    kid = _user(db, "kid")
    _limit(client, db, kid, max_content_rating="teen")
    headers = bearer_headers(kid.id)
    similar = {"data": [{"novel_id": 2}, {"novel_id": 3}, {"novel_id": 1}]}
    with _patch_metadata(), patch("app.services.metadata_client.get_similar_novels", AsyncMock(return_value=similar)), \
            patch("app.services.metadata_client.get_hiatus_status", AsyncMock(return_value={})):
        rows = client.get("/discovery/novels/3/similar", headers=headers).json()["data"]
        assert [row["novel_id"] for row in rows] == [3, 1]
        blocked = client.get("/discovery/novels/2", headers=headers)
        assert blocked.status_code == 403 and "content limits" in blocked.json()["detail"]
        assert client.get("/discovery/novels/2/similar", headers=headers).status_code == 403
        assert client.get("/stories/2", headers=headers).status_code == 403
        assert client.get("/discovery/novels/1", headers=headers).status_code == 200
        kid_lib = _library(db, kid)
        own_grim = _novel(db, kid_lib, 2)
        assert client.get(f"/novel/{own_grim.id}?library_id={kid_lib.id}", headers=headers).status_code == 403


def test_recommendations_are_limited(client, db):
    kid = _user(db, "kid")
    _limit(client, db, kid, max_content_rating="general", blocked_tags=["gore"])
    rows = [{"id": 1, "title": "Gentle", "content_rating": "general"},
            {"id": 3, "title": "Teen drama", "content_rating": "teen"}]
    with patch("app.routers.recommendations.metadata_client.get_novel_metadata", AsyncMock(return_value={"tags": ["Cozy"]})), \
            patch("app.routers.recommendations.metadata_client.list_novels_metadata", AsyncMock(return_value={"data": rows})) as listing, \
            patch("app.routers.recommendations.personal_for_novels", return_value={}):
        from app.models.follow import UserNovelFollow
        followed = _novel(db, _library(db, kid), 4)
        db.add(UserNovelFollow(user_id=kid.id, novel_id=followed.id))
        db.commit()
        data = client.get("/recommendations", headers=bearer_headers(kid.id)).json()["data"]
    assert [row["id"] for row in data] == [1]
    assert listing.call_args.kwargs["content_rating"] == ["general"]
    assert listing.call_args.kwargs["exclude_tag"] == ["gore"]


def test_shared_shelf_hides_stories_beyond_recipient_limits(client, db):
    owner, kid, shelf, *_ = _household(db)
    client.put(f"/shelves/{shelf.id}/shares/{kid.id}", json={"permission": "view"}, headers=bearer_headers(owner.id))
    _limit(client, db, kid, max_content_rating="teen")
    with _patch_metadata():
        stories = client.get(f"/shelves/{shelf.id}/stories", headers=bearer_headers(kid.id)).json()["stories"]
        owner_view = client.get(f"/shelves/{shelf.id}/stories", headers=bearer_headers(owner.id)).json()["stories"]
    assert [row["metadata_id"] for row in stories] == [1]
    assert [row["metadata_id"] for row in owner_view] == [1, 2]


def test_import_results_skip_stories_beyond_limits(client, db, test_user, test_library, auth_headers, monkeypatch):
    test_user.max_content_rating = "teen"
    db.commit()
    monkeypatch.setattr("app.services.metadata_client.scrape_novel_by_url", _metadata_scrape())
    text = "https://www.royalroad.com/fiction/501/a https://www.royalroad.com/fiction/502/b"
    job = client.post("/imports/urls", json={"library_id": test_library.id, "text": text}, headers=auth_headers).json()
    with _patch_metadata():
        asyncio.run(imports.run_import_job(job["id"], TestingSessionLocal, scrape=FakeScrape()))
    report = client.get(f"/imports/{job['id']}", headers=auth_headers).json()
    assert sorted(item["status"] for item in report["items"]) == ["linked", "restricted"]
    db.expire_all()
    assert [novel.metadata_id for novel in db.query(Novel).filter(Novel.library_id == test_library.id)] == [1001]


def test_add_by_link_refuses_known_story_beyond_limits(client, db, test_user, test_library, auth_headers, monkeypatch):
    test_user.max_content_rating = "teen"
    db.commit()
    monkeypatch.setattr("app.services.metadata_client.scrape_novel_by_url",
                        AsyncMock(return_value={"success": True, "novel_id": 2, "message": "exists"}))
    with _patch_metadata():
        response = client.post("/novel/", json={"library_id": test_library.id, "url": "https://www.royalroad.com/fiction/2/grim"},
                               headers=auth_headers)
    assert response.status_code == 403
    assert db.query(Novel).filter(Novel.library_id == test_library.id).count() == 0


def test_add_by_link_drops_new_story_beyond_limits_after_scrape(db, test_user, test_library):
    from app.routers.novel import scrape_within_limits

    test_user.max_content_rating = "teen"
    db.commit()
    kept = Novel(title="New", url="https://www.royalroad.com/fiction/1001/a", library_id=test_library.id, novel_site="royalroad",
                 metadata_id=1001, scrape_status="pending")
    dropped = Novel(title="New", url="https://www.royalroad.com/fiction/1002/b", library_id=test_library.id, novel_site="royalroad",
                    metadata_id=1002, scrape_status="pending")
    db.add_all([kept, dropped])
    db.commit()
    with _patch_metadata():
        for novel in (kept, dropped):
            scrape_within_limits(novel.id, novel.metadata_id, TestingSessionLocal, None, test_user.id, scrape=FakeScrape())
    db.expire_all()
    assert [novel.metadata_id for novel in db.query(Novel).filter(Novel.library_id == test_library.id)] == [1001]
