import copy
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.blocklist import BlocklistEntry
from app.models.novel import Novel
from app.models.novel_personal import NovelPersonalData, NovelUserTag
from app.models.shelf import Shelf, ShelfNovel
from tests.auth_helpers import bearer_headers
from tests.routes.test_user_data import ROYAL_ROAD_URL, _seed, _wipe


@pytest.fixture
def scrape(monkeypatch):
    scrape_call = AsyncMock(return_value={"success": True, "novel_id": 99, "message": "ok"})
    background = MagicMock()
    monkeypatch.setattr("app.services.metadata_client.scrape_novel_by_url", scrape_call)
    monkeypatch.setattr("app.routers.user_data.scrape_novel_background", background)
    return scrape_call, background


def _seed_organization(db, user):
    novel = _seed(db, user)
    db.add(NovelPersonalData(user_id=user.id, novel_id=novel.id, notes="Read the prologue twice", rating=4))
    db.add_all([
        NovelUserTag(user_id=user.id, novel_id=novel.id, tag="cozy"),
        NovelUserTag(user_id=user.id, novel_id=novel.id, tag="slow burn"),
    ])
    shelf = Shelf(user_id=user.id, name="Favourites", position=1)
    db.add(shelf)
    db.flush()
    db.add(ShelfNovel(shelf_id=shelf.id, novel_id=novel.id, position=1))
    db.add(BlocklistEntry(user_id=user.id, kind="tag", value="gore"))
    db.commit()
    return novel


def _organization_wipe(db, user):
    _wipe(db, user)
    # SQLite does not enforce ON DELETE CASCADE here, so drop the links first.
    shelf_ids = [shelf.id for shelf in db.query(Shelf).filter(Shelf.user_id == user.id).all()]
    db.query(ShelfNovel).filter(ShelfNovel.shelf_id.in_(shelf_ids)).delete(synchronize_session=False)
    for model in (Shelf, BlocklistEntry, NovelPersonalData, NovelUserTag):
        db.query(model).filter(model.user_id == user.id).delete()
    db.commit()


def test_export_includes_optional_organization_keys(client, db, test_user):
    _seed_organization(db, test_user)

    document = client.get("/me/export", headers=bearer_headers(test_user.id)).json()

    assert document["version"] == 1
    novel = document["libraries"][0]["novels"][0]
    assert novel["personal"] == {"notes": "Read the prologue twice", "rating": 4, "user_tags": ["cozy", "slow burn"]}
    assert document["shelves"] == [{"name": "Favourites", "position": 1, "novels": [{"library": "Reading", "url": ROYAL_ROAD_URL}]}]
    assert document["blocklist"] == [{"kind": "tag", "value": "gore"}]
    assert "novel_id" not in str(document)


def test_organization_round_trip_is_idempotent(client, db, test_user, scrape):
    headers = bearer_headers(test_user.id)
    _seed_organization(db, test_user)
    exported = client.get("/me/export", headers=headers).json()
    _organization_wipe(db, test_user)
    _wipe(db, test_user)

    first = client.post("/me/import", json=exported, headers=headers)
    assert first.status_code == 200, first.text
    summary = first.json()["summary"]
    assert summary["personal_applied"] == 1
    assert summary["shelves_created"] == 1
    assert summary["shelf_links_added"] == 1
    assert summary["shelf_links_missing"] == 0
    assert summary["blocklist_created"] == 1

    shelf = db.query(Shelf).filter(Shelf.user_id == test_user.id).one()
    novel = db.query(Novel).filter(Novel.url == ROYAL_ROAD_URL).one()
    assert db.query(ShelfNovel).filter(ShelfNovel.shelf_id == shelf.id, ShelfNovel.novel_id == novel.id).count() == 1
    personal = db.query(NovelPersonalData).filter(NovelPersonalData.user_id == test_user.id).one()
    assert (personal.notes, personal.rating) == ("Read the prologue twice", 4)
    assert sorted(t.tag for t in db.query(NovelUserTag).filter(NovelUserTag.user_id == test_user.id).all()) == ["cozy", "slow burn"]

    counts_before = (
        db.query(Shelf).count(),
        db.query(ShelfNovel).count(),
        db.query(NovelPersonalData).count(),
        db.query(NovelUserTag).count(),
        db.query(BlocklistEntry).count(),
    )
    second = client.post("/me/import", json=exported, headers=headers)
    assert second.status_code == 200, second.text
    second_summary = second.json()["summary"]
    assert second_summary["shelves_created"] == 0
    assert second_summary["shelf_links_added"] == 0
    assert second_summary["personal_applied"] == 0
    assert second_summary["blocklist_created"] == 0
    counts_after = (
        db.query(Shelf).count(),
        db.query(ShelfNovel).count(),
        db.query(NovelPersonalData).count(),
        db.query(NovelUserTag).count(),
        db.query(BlocklistEntry).count(),
    )
    assert counts_after == counts_before


def test_import_keeps_local_personal_values_and_merges_tags(client, db, test_user, scrape):
    headers = bearer_headers(test_user.id)
    _seed_organization(db, test_user)
    exported = client.get("/me/export", headers=headers).json()
    local_novel = db.query(Novel).filter(Novel.url == ROYAL_ROAD_URL).one()
    db.query(NovelPersonalData).filter(NovelPersonalData.user_id == test_user.id).update({"rating": 2, "notes": "Local note"})
    db.add(NovelUserTag(user_id=test_user.id, novel_id=local_novel.id, tag="local"))
    db.commit()

    response = client.post("/me/import", json=exported, headers=headers)

    assert response.status_code == 200
    assert response.json()["summary"]["personal_kept_local"] == 1
    personal = db.query(NovelPersonalData).filter(NovelPersonalData.user_id == test_user.id).one()
    assert (personal.notes, personal.rating) == ("Local note", 2)
    tags = sorted(t.tag for t in db.query(NovelUserTag).filter(NovelUserTag.user_id == test_user.id).all())
    assert tags == ["cozy", "local", "slow burn"]


def test_import_reports_shelf_members_missing_from_instance(client, db, test_user, scrape):
    headers = bearer_headers(test_user.id)
    document = {
        "format": "nexus-user-export",
        "version": 1,
        "libraries": [],
        "saved_searches": [],
        "shelves": [{"name": "Ghosts", "novels": [{"library": "Nowhere", "url": "https://example.test/x"}]}],
    }

    response = client.post("/me/import", json=document, headers=headers)

    assert response.status_code == 200
    assert response.json()["shelves"][0]["links_missing"] == 1
    assert response.json()["summary"]["shelf_links_missing"] == 1


def test_older_exports_without_organization_keys_still_import(client, db, test_user, scrape):
    document = {"format": "nexus-user-export", "version": 1, "libraries": [], "saved_searches": []}

    response = client.post("/me/import", json=copy.deepcopy(document), headers=bearer_headers(test_user.id))

    assert response.status_code == 200
    assert response.json()["shelves"] == []
    assert response.json()["blocklist"] == []


@pytest.mark.parametrize("bad", [{"kind": "planet", "value": "x"}, {"kind": "tag", "value": ""}])
def test_import_rejects_invalid_blocklist_entries(client, db, test_user, bad):
    document = {"format": "nexus-user-export", "version": 1, "blocklist": [bad]}

    response = client.post("/me/import", json=document, headers=bearer_headers(test_user.id))

    assert response.status_code == 422
