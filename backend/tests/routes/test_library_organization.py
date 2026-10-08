from datetime import datetime
from unittest.mock import AsyncMock, patch

from app.models.blocklist import BlocklistEntry
from app.models.chapter import Chapter
from app.models.library import Library
from app.models.novel import Novel
from app.models.novel_personal import NovelPersonalData
from app.models.reading_progress import ReadingProgress
from app.models.user import User
from app.services.blocklist_service import apply_blocklist, merged_exclusions
from app.services.recommendation_reasons import ReasonSource, build_reasons
from tests.auth_helpers import bearer_headers

EMPTY_PAGE = {"data": [], "next_cursor": None, "has_more": False}


def _user(db, name: str) -> User:
    user = User(username=name, password="hashed_password_here")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _library(db, user: User, name: str = "Reading") -> Library:
    library = Library(name=name, user_id=user.id)
    db.add(library)
    db.commit()
    db.refresh(library)
    return library


def _novel(db, library: Library, title: str, *, url: str | None = None, metadata_id: int | None = None, **extra) -> Novel:
    novel = Novel(
        title=title,
        url=url or f"https://www.royalroad.com/fiction/{abs(hash(title)) % 100000}",
        library_id=library.id,
        novel_site="royalroad",
        metadata_id=metadata_id,
        **extra,
    )
    db.add(novel)
    db.commit()
    db.refresh(novel)
    return novel


# ---------------------------------------------------------------- blocklist


def test_blocklist_crud_and_normalisation(client, db, test_user):
    headers = bearer_headers(test_user.id)

    created = client.post("/blocklist", json={"kind": "tag", "value": "  gore  "}, headers=headers)
    assert created.status_code == 201
    assert created.json()["value"] == "gore"

    again = client.post("/blocklist", json={"kind": "tag", "value": "gore"}, headers=headers)
    assert again.json()["id"] == created.json()["id"]

    assert client.post("/blocklist", json={"kind": "planet", "value": "x"}, headers=headers).status_code == 422
    assert client.post("/blocklist", json={"kind": "tag", "value": "   "}, headers=headers).status_code == 422

    listed = client.get("/blocklist", headers=headers).json()
    assert [entry["value"] for entry in listed] == ["gore"]

    assert client.delete(f"/blocklist/{created.json()['id']}", headers=headers).status_code == 200
    assert client.get("/blocklist", headers=headers).json() == []


def test_blocklist_is_per_user(client, db, test_user):
    other = _user(db, "other")
    client.post("/blocklist", json={"kind": "author", "value": "Alice"}, headers=bearer_headers(other.id))

    assert client.get("/blocklist", headers=bearer_headers(test_user.id)).json() == []
    entry = db.query(BlocklistEntry).filter(BlocklistEntry.user_id == other.id).one()
    assert client.delete(f"/blocklist/{entry.id}", headers=bearer_headers(test_user.id)).status_code == 404


def test_merged_exclusions_combine_request_and_blocklist(db, test_user):
    db.add_all([
        BlocklistEntry(user_id=test_user.id, kind="tag", value="Gore"),
        BlocklistEntry(user_id=test_user.id, kind="word", value="harem"),
    ])
    db.commit()

    merged = merged_exclusions(db, test_user, exclude_tag=["gore", "necromancy"], exclude_text=None)

    assert merged["exclude_tag"] == ["gore", "necromancy"]
    assert merged["exclude_text"] == ["harem"]
    assert merged["exclude_author"] is None


def test_apply_blocklist_checks_tags_genres_authors_and_words(db, test_user):
    db.add_all([
        BlocklistEntry(user_id=test_user.id, kind="tag", value="gore"),
        BlocklistEntry(user_id=test_user.id, kind="genre", value="horror"),
        BlocklistEntry(user_id=test_user.id, kind="author", value="Alice"),
        BlocklistEntry(user_id=test_user.id, kind="word", value="harem"),
    ])
    db.commit()
    items = [
        {"id": 1, "title": "Clean", "tags": [{"name": "time loop"}]},
        {"id": 2, "title": "Bloody", "tags": [{"name": "Gore"}]},
        {"id": 3, "title": "Scary", "genres": ["Horror"]},
        {"id": 4, "title": "Written", "author": "alice"},
        {"id": 5, "title": "Summary words", "summary": "A HAREM comedy"},
    ]

    kept = apply_blocklist(db, test_user, items)

    assert [item["id"] for item in kept] == [1]


def test_discovery_merges_blocklist_and_drops_blocked_rows(client, db, test_user):
    db.add(BlocklistEntry(user_id=test_user.id, kind="tag", value="gore"))
    db.commit()
    page = {
        "data": [
            {"id": 1, "title": "Fine", "tags": ["time loop"]},
            {"id": 2, "title": "Bloody", "tags": [{"name": "gore"}]},
        ],
        "next_cursor": None,
        "has_more": False,
    }
    list_mock = AsyncMock(return_value=page)
    with patch("app.routers.discovery.metadata_client.list_novels_metadata", list_mock):
        response = client.get("/discovery/novels/?exclude_tag=necromancy", headers=bearer_headers(test_user.id))

    assert response.status_code == 200
    assert [row["id"] for row in response.json()["data"]] == [1]
    assert list_mock.await_args.kwargs["exclude_tag"] == ["necromancy", "gore"]


def test_discovery_without_blocklist_leaves_request_unchanged(client, db, test_user):
    list_mock = AsyncMock(return_value=EMPTY_PAGE)
    with patch("app.routers.discovery.metadata_client.list_novels_metadata", list_mock):
        client.get("/discovery/novels/?exclude_tag=gore", headers=bearer_headers(test_user.id))

    assert list_mock.await_args.kwargs["exclude_tag"] == ["gore"]
    assert list_mock.await_args.kwargs["exclude_author"] is None


def test_similar_results_get_reasons_and_blocklist(client, db, test_user):
    library = _library(db, test_user)
    source = _novel(db, library, "Source", metadata_id=7, author="Writer")
    db.add(NovelPersonalData(user_id=test_user.id, novel_id=source.id, rating=5))
    db.add(BlocklistEntry(user_id=test_user.id, kind="tag", value="gore"))
    db.commit()

    similar = {"data": [
        {"novel_id": 8, "title": "Sibling", "author": "Writer", "explanation": "metadata"},
        {"novel_id": 9, "title": "Bloody sibling", "author": "Someone", "explanation": "metadata"},
    ]}
    metadata = {
        7: {"title": "Source", "author": "Writer", "tags": [{"name": "time loop"}, {"name": "magic"}]},
        8: {"title": "Sibling", "author": "Writer", "tags": [{"name": "magic"}]},
        9: {"title": "Bloody sibling", "author": "Someone", "tags": [{"name": "gore"}]},
    }

    async def fake_metadata(novel_id):
        return metadata[novel_id]

    with patch("app.routers.discovery.metadata_client.get_similar_novels", AsyncMock(return_value=similar)), \
            patch("app.routers.discovery.metadata_client.get_novel_metadata", side_effect=fake_metadata):
        response = client.get(f"/discovery/novels/{source.metadata_id}/similar", headers=bearer_headers(test_user.id))

    rows = response.json()["data"]
    assert [row["novel_id"] for row in rows] == [8]
    assert rows[0]["reasons"] == [
        "Similar to Source you rated 5★",
        "Shares tags: magic",
        "Same author: Writer",
    ]


# ---------------------------------------------------------------- recommendations


def test_recommendation_reasons_name_rating_shared_tags_and_author():
    candidate = {"title": "Next", "author": "Writer", "tags": [{"name": "Time Loop"}, {"name": "magic"}]}
    sources = [
        ReasonSource(title="Source", terms=["time loop", "magic"], author="Writer", rating=5, via_terms=["time loop"]),
    ]

    assert build_reasons(candidate, sources) == [
        "Similar to Source you rated 5★",
        "Shares tags: time loop, magic",
        "Same author: Writer",
    ]


def test_recommendation_reasons_fall_back_to_title():
    reasons = build_reasons({"title": "Plain"}, [ReasonSource(title="Source", terms=[], rating=None)])
    assert reasons == ["Similar to Source"]
    assert build_reasons({"title": "Plain"}, []) == []


def test_recommendations_endpoint_returns_reasons_and_filters_blocked(client, db, test_user):
    library = _library(db, test_user)
    followed = _novel(db, library, "Followed", metadata_id=20, author="Anna")
    from app.models.follow import UserNovelFollow

    db.add(UserNovelFollow(user_id=test_user.id, novel_id=followed.id, state="reading", followed_at=datetime(2026, 9, 1)))
    db.add(NovelPersonalData(user_id=test_user.id, novel_id=followed.id, rating=5))
    db.add(BlocklistEntry(user_id=test_user.id, kind="tag", value="gore"))
    db.commit()

    async def fake_list(**kwargs):
        return {"data": [
            {"id": 31, "title": "Match", "author": "Bob", "tags": [{"name": "time loop"}]},
            {"id": 32, "title": "Gory match", "author": "Bob", "tags": [{"name": "time loop"}, {"name": "gore"}]},
        ]}

    with patch("app.routers.recommendations.metadata_client.get_novel_metadata",
               AsyncMock(return_value={"title": "Followed", "author": "Anna", "tags": [{"name": "time loop"}]})), \
            patch("app.routers.recommendations.metadata_client.list_novels_metadata", side_effect=fake_list):
        response = client.get("/recommendations", headers=bearer_headers(test_user.id))

    rows = response.json()["data"]
    assert [row["id"] for row in rows] == [31]
    assert rows[0]["reasons"] == ["Similar to Followed you rated 5★", "Shares tags: time loop"]
    assert rows[0]["explanation"] == rows[0]["reasons"][0]


# ---------------------------------------------------------------- shelves


def test_shelves_crud_and_novel_membership(client, db, test_user):
    headers = bearer_headers(test_user.id)
    library = _library(db, test_user)
    novel = _novel(db, library, "Shelved")

    first = client.post("/shelves", json={"name": "  Favourites "}, headers=headers).json()
    second = client.post("/shelves", json={"name": "To read"}, headers=headers).json()
    assert first["name"] == "Favourites"
    assert first["position"] < second["position"]
    assert client.post("/shelves", json={"name": "to read"}, headers=headers).status_code == 409

    added = client.put(f"/shelves/{first['id']}/novels/{novel.id}", headers=headers)
    assert added.json()["novel_ids"] == [novel.id]
    assert client.put(f"/shelves/{second['id']}/novels/{novel.id}", headers=headers).status_code == 200

    renamed = client.patch(f"/shelves/{first['id']}", json={"name": "Best", "position": 0}, headers=headers).json()
    assert renamed["name"] == "Best"

    removed = client.delete(f"/shelves/{first['id']}/novels/{novel.id}", headers=headers).json()
    assert removed["novel_ids"] == []

    listed = client.get("/shelves", headers=headers).json()
    assert [shelf["name"] for shelf in listed] == ["Best", "To read"]

    assert client.delete(f"/shelves/{second['id']}", headers=headers).status_code == 200
    assert [shelf["name"] for shelf in client.get("/shelves", headers=headers).json()] == ["Best"]


def test_shelf_names_are_unique_per_user(client, db, test_user):
    headers = bearer_headers(test_user.id)
    client.post("/shelves", json={"name": "Dup"}, headers=headers)

    assert client.post("/shelves", json={"name": "dup"}, headers=headers).status_code == 409
    other = _user(db, "other")
    assert client.post("/shelves", json={"name": "Dup"}, headers=bearer_headers(other.id)).status_code == 201


def test_shelves_and_novels_are_private_to_their_owner(client, db, test_user):
    other = _user(db, "other")
    other_library = _library(db, other, "Theirs")
    their_novel = _novel(db, other_library, "Not mine")
    my_shelf = client.post("/shelves", json={"name": "Mine"}, headers=bearer_headers(test_user.id)).json()

    response = client.put(f"/shelves/{my_shelf['id']}/novels/{their_novel.id}", headers=bearer_headers(test_user.id))
    assert response.status_code == 404
    other_shelf = client.post("/shelves", json={"name": "Theirs"}, headers=bearer_headers(other.id)).json()
    assert client.patch(f"/shelves/{other_shelf['id']}", json={"name": "x"}, headers=bearer_headers(test_user.id)).status_code == 404


def test_library_list_filters_by_shelf(client, db, test_user):
    headers = bearer_headers(test_user.id)
    library = _library(db, test_user)
    keep = _novel(db, library, "Keep")
    _novel(db, library, "Skip")
    shelf = client.post("/shelves", json={"name": "Keep shelf"}, headers=headers).json()
    client.put(f"/shelves/{shelf['id']}/novels/{keep.id}", headers=headers)

    rows = client.get(f"/novel/?library_id={library.id}&shelf_id={shelf['id']}", headers=headers).json()

    assert [row["title"] for row in rows] == ["Keep"]


# ---------------------------------------------------------------- personal data


def test_personal_data_round_trip_and_validation(client, db, test_user):
    headers = bearer_headers(test_user.id)
    library = _library(db, test_user)
    novel = _novel(db, library, "Noted")
    url = f"/personal/novels/{novel.id}"

    saved = client.put(url, json={"notes": "  Remember the ending  ", "rating": 4, "user_tags": ["Cozy", " cozy ", "slow burn"]}, headers=headers)
    assert saved.status_code == 200
    body = saved.json()
    assert body["notes"] == "Remember the ending"
    assert body["rating"] == 4
    assert body["user_tags"] == ["cozy", "slow burn"]

    assert client.get(url, headers=headers).json()["rating"] == 4
    assert client.put(url, json={"rating": 6}, headers=headers).status_code == 422
    assert client.put(url, json={"rating": 0}, headers=headers).status_code == 422

    cleared = client.put(url, json={"notes": "", "rating": None, "user_tags": []}, headers=headers).json()
    assert cleared == {
        "novel_id": novel.id,
        "notes": None,
        "rating": None,
        "user_tags": [],
        "followed_categories": ["story"],
        "auto_download": False,
        "keep_ahead": 10,
    }


def test_personal_data_hidden_from_other_users(client, db, test_user):
    other = _user(db, "other")
    novel = _novel(db, _library(db, other, "Theirs"), "Private")

    assert client.get(f"/personal/novels/{novel.id}", headers=bearer_headers(test_user.id)).status_code == 404
    assert client.put(f"/personal/novels/{novel.id}", json={"rating": 3}, headers=bearer_headers(test_user.id)).status_code == 404


def test_user_tag_autocomplete_orders_by_use(client, db, test_user):
    headers = bearer_headers(test_user.id)
    library = _library(db, test_user)
    first = _novel(db, library, "A")
    second = _novel(db, library, "B")
    client.put(f"/personal/novels/{first.id}", json={"user_tags": ["cozy", "slow burn"]}, headers=headers)
    client.put(f"/personal/novels/{second.id}", json={"user_tags": ["cozy"]}, headers=headers)

    assert client.get("/personal/tags", headers=headers).json()["tags"] == ["cozy", "slow burn"]
    assert client.get("/personal/tags?q=slo", headers=headers).json()["tags"] == ["slow burn"]


def test_library_personal_map_and_user_tag_and_rating_filters(client, db, test_user):
    headers = bearer_headers(test_user.id)
    library = _library(db, test_user)
    top = _novel(db, library, "Top")
    mid = _novel(db, library, "Mid")
    _novel(db, library, "Unrated")
    client.put(f"/personal/novels/{top.id}", json={"rating": 5, "user_tags": ["cozy"], "notes": "x"}, headers=headers)
    client.put(f"/personal/novels/{mid.id}", json={"rating": 3, "user_tags": ["cozy"]}, headers=headers)

    personal = client.get(f"/personal/library/{library.id}", headers=headers).json()["novels"]
    assert personal[str(top.id)]["has_notes"] is True
    assert personal[str(top.id)]["user_tags"] == ["cozy"]

    by_tag = client.get(f"/novel/?library_id={library.id}&user_tag=Cozy", headers=headers).json()
    assert sorted(row["title"] for row in by_tag) == ["Mid", "Top"]

    by_rating = client.get(f"/novel/?library_id={library.id}&min_rating=4", headers=headers).json()
    assert [row["title"] for row in by_rating] == ["Top"]


def test_library_sort_by_personal_rating_puts_unrated_last(client, db, test_user):
    headers = bearer_headers(test_user.id)
    library = _library(db, test_user)
    low = _novel(db, library, "Low")
    unrated = _novel(db, library, "Unrated")
    high = _novel(db, library, "High")
    client.put(f"/personal/novels/{low.id}", json={"rating": 2}, headers=headers)
    client.put(f"/personal/novels/{high.id}", json={"rating": 5}, headers=headers)

    rows = client.get(f"/novel/?library_id={library.id}&sort_by=personal_rating", headers=headers).json()

    assert [row["title"] for row in rows] == ["High", "Low", "Unrated"]
    assert unrated.id in [row["id"] for row in rows]


def test_library_sort_updated_since_read_puts_new_chapters_first(client, db, test_user):
    headers = bearer_headers(test_user.id)
    library = _library(db, test_user)
    caught_up = _novel(db, library, "Caught up", updated_date=datetime(2026, 10, 7))
    behind = _novel(db, library, "Behind", updated_date=datetime(2026, 9, 1))
    unread = _novel(db, library, "Never opened", updated_date=datetime(2026, 10, 8))
    for novel, read_to, count in ((caught_up, 3, 3), (behind, 1, 4)):
        for number in range(1, count + 1):
            db.add(Chapter(novel_id=novel.id, chapter_number=number, title=f"C{number}"))
        db.add(ReadingProgress(user_id=test_user.id, novel_id=novel.id, chapter_number=read_to, position=0, percent=50))
    db.add(Chapter(novel_id=unread.id, chapter_number=1, title="C1"))
    db.commit()

    rows = client.get(f"/novel/?library_id={library.id}&sort_by=updated_since_read", headers=headers).json()

    # Novels with new chapters past the last read come first; the rest by latest update.
    assert [row["title"] for row in rows] == ["Behind", "Never opened", "Caught up"]
