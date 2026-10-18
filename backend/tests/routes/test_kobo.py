"""Native Kobo sync. Request and response shapes follow Calibre-Web's kobo.py and
Komga's Kobo support (docs/kobo-sync.md); no real device is involved."""

import base64
import json
import stat
import zipfile
from io import BytesIO

import pytest

from app.models.chapter import Chapter, ContentStatus
from app.models.ereader import KoboDevice, KoboSyncedBook
from app.models.library import Library
from app.models.novel import Novel
from app.models.reading_progress import ReadingProgress
from app.models.shelf import Shelf, ShelfNovel
from app.models.user import User
from config.settings import settings
from tests.auth_helpers import bearer_headers

SYNC_TOKEN = "x-kobo-synctoken"

# Shapes the device sends (as handled by Calibre-Web's HandleStateRequest).
def device_state(entitlement: str, *, source: str, content: float, overall: float, status: str = "Reading") -> dict:
    stamp = "2026-10-09T08:00:00Z"
    return {
        "ReadingStates": [
            {
                "EntitlementId": entitlement,
                "Created": stamp,
                "LastModified": stamp,
                "PriorityTimestamp": stamp,
                "StatusInfo": {"LastModified": stamp, "Status": status, "TimesStartedReading": 1, "LastTimeStartedReading": stamp},
                "Statistics": {"LastModified": stamp, "SpentReadingMinutes": 12, "RemainingTimeMinutes": 40},
                "CurrentBookmark": {
                    "LastModified": stamp,
                    "ProgressPercent": overall,
                    "ContentSourceProgressPercent": content,
                    "Location": {"Value": "kobo.7.2", "Type": "KoboSpan", "Source": source},
                },
            }
        ]
    }


# A Calibre-Web sync token (base64 JSON with its own fields): not ours, so a full resync.
CALIBRE_WEB_TOKEN = base64.b64encode(
    json.dumps({"version": "1-1-0", "data": {"raw_kobo_store_token": "", "books_last_modified": -62135596800}}).encode()
).decode()


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DOWNLOAD_PATH", str(tmp_path))
    monkeypatch.setattr(settings, "NEXUS_KEPUBIFY_PATH", str(tmp_path / "no-kepubify"))
    monkeypatch.setattr(settings, "NEXUS_KOBO_STORE_PROXY", False)
    monkeypatch.setattr(settings, "NEXUS_KOBO_BASE_URL", "")


def add_novel(db, library: Library, title: str, chapters: int = 3) -> Novel:
    novel = Novel(title=title, author="Author A", library_id=library.id, description="<p>About <b>things</b>.</p>")
    db.add(novel)
    db.flush()
    for number in range(1, chapters + 1):
        db.add(Chapter(novel_id=novel.id, chapter_number=number, title=f"Chapter {number}",
                       content=f"Paragraph {number}.", content_status=ContentStatus.PRESENT))
    db.commit()
    return novel


def make_device(client, auth_headers, **body) -> dict:
    response = client.post("/kobo-devices", json={"label": "Libra", **body}, headers=auth_headers)
    assert response.status_code == 201, response.text
    return response.json()


def shelve(db, shelf_id: int, novel: Novel) -> None:
    db.add(ShelfNovel(shelf_id=shelf_id, novel_id=novel.id))
    db.commit()


def sync(client, token: str, sync_token: str | None = None):
    headers = {SYNC_TOKEN: sync_token} if sync_token else {}
    response = client.get(f"/kobo/{token}/v1/library/sync", headers=headers)
    assert response.status_code == 200, response.text
    return response


def books(items: list[dict]) -> list[tuple[str, dict]]:
    return [(kind, item[kind]) for item in items for kind in item if kind.endswith("Entitlement")]


@pytest.fixture
def setup(client, db, test_user, test_library, auth_headers):
    device = make_device(client, auth_headers)
    novel = add_novel(db, test_library, "Mother of Learning")
    shelve(db, device["shelf_id"], novel)
    return device, novel


def test_device_creation_makes_kobo_shelf_and_shows_token_once(client, db, test_user, auth_headers):
    device = make_device(client, auth_headers)
    assert device["shelf_name"] == "Kobo"
    assert device["endpoint_path"] == f"/kobo/{device['token']}"
    stored = db.query(KoboDevice).one()
    assert stored.token_hash != device["token"] and len(stored.token_hash) == 64

    listing = client.get("/kobo-devices", headers=auth_headers).json()
    assert listing["kepub"] is False
    assert [item["id"] for item in listing["devices"]] == [device["id"]]
    assert "token" not in listing["devices"][0]
    # A second device reuses the shelf.
    make_device(client, auth_headers)
    assert db.query(Shelf).filter(Shelf.name == "Kobo").count() == 1


def test_initialization_points_the_device_at_nexus(client, setup):
    device, _ = setup
    response = client.get(f"/kobo/{device['token']}/v1/initialization", headers={"x-real-ip": "10.0.0.2", "host": "nexus.lan:8180"})
    assert response.status_code == 200
    assert response.headers["x-kobo-apitoken"] == "e30="
    resources = response.json()["Resources"]
    base = f"http://nexus.lan:8180/api/kobo/{device['token']}"
    assert resources["library_sync"] == f"{base}/v1/library/sync"
    assert resources["reading_state"] == base + "/v1/library/{Ids}/state"
    assert resources["image_url_quality_template"].startswith(base + "/{ImageId}/")
    assert resources["image_host"] == "http://nexus.lan:8180"
    # Without the opt-in proxy, no API resource leads to Kobo's servers.
    assert not [value for value in resources.values() if "kobo.com" in value]


def test_unknown_and_revoked_tokens_are_refused_and_rate_limited(client, db, setup, auth_headers):
    device, _ = setup
    assert client.get("/kobo/not-a-token/v1/initialization").status_code == 401
    assert client.delete(f"/kobo-devices/{device['id']}", headers=auth_headers).status_code == 204
    assert client.get(f"/kobo/{device['token']}/v1/library/sync").status_code == 401
    assert client.get("/kobo-devices", headers=auth_headers).json()["devices"] == []
    statuses = {client.get(f"/kobo/wrong-{n}/v1/initialization").status_code for n in range(30)}
    assert 429 in statuses


def test_initial_sync_sends_the_shelf_as_new_entitlements(client, db, setup, test_library):
    device, novel = setup
    add_novel(db, test_library, "Not on the shelf")
    response = sync(client, device["token"])
    assert SYNC_TOKEN in response.headers
    assert "x-kobo-sync" not in response.headers
    items = response.json()
    entries = books(items)
    assert [kind for kind, _ in entries] == ["NewEntitlement"]
    entry = entries[0][1]
    entitlement, metadata = entry["BookEntitlement"], entry["BookMetadata"]
    assert set(entitlement) == {
        "Accessibility", "ActivePeriod", "Created", "CrossRevisionId", "Id", "IsRemoved",
        "IsHiddenFromArchive", "IsLocked", "LastModified", "OriginCategory", "RevisionId", "Status",
    }
    assert entitlement["IsRemoved"] is False and entitlement["Status"] == "Active"
    assert entitlement["Created"].endswith("Z") and "T" in entitlement["Created"]
    assert metadata["Title"] == "Mother of Learning"
    assert metadata["Contributors"] == ["Author A"]
    assert metadata["Description"] == "About  things ."
    assert metadata["EntitlementId"] == metadata["RevisionId"] == entitlement["Id"]
    [download] = metadata["DownloadUrls"]
    assert download["Format"] == "EPUB3" and download["Platform"] == "Generic" and download["Size"] > 0
    assert f"/kobo/{device['token']}/download/{entitlement['Id']}/epub" in download["Url"]
    # No reading state yet; the shelf arrives as a collection.
    assert "ReadingState" not in entry
    [tag] = [item["NewTag"]["Tag"] for item in items if "NewTag" in item]
    assert tag["Name"] == "Kobo" and tag["Type"] == "UserTag"
    assert tag["Items"] == [{"RevisionId": entitlement["Id"], "Type": "ProductRevisionTagItem"}]


def test_incremental_sync_sends_changes_and_removals(client, db, setup, test_library):
    device, novel = setup
    first = sync(client, device["token"])
    token = first.headers[SYNC_TOKEN]
    assert sync(client, device["token"], token).json() == []

    db.add(Chapter(novel_id=novel.id, chapter_number=4, title="Chapter 4", content="New.", content_status=ContentStatus.PRESENT))
    db.commit()
    changed = books(sync(client, device["token"], token).json())
    assert [kind for kind, _ in changed] == ["ChangedEntitlement"]
    assert changed[0][1]["BookEntitlement"]["IsRemoved"] is False

    db.query(ShelfNovel).delete()
    db.commit()
    items = sync(client, device["token"], token).json()
    removed = books(items)
    assert [kind for kind, _ in removed] == ["ChangedEntitlement"]
    assert removed[0][1]["BookEntitlement"]["IsRemoved"] is True
    assert "BookMetadata" not in removed[0][1]
    assert [item["ChangedTag"]["Tag"]["Items"] for item in items if "ChangedTag" in item] == [[]]
    assert sync(client, device["token"], token).json() == []


def test_missing_or_foreign_sync_token_resyncs_everything(client, setup):
    device, _ = setup
    token = sync(client, device["token"]).headers[SYNC_TOKEN]
    assert sync(client, device["token"], token).json() == []
    again = books(sync(client, device["token"], CALIBRE_WEB_TOKEN).json())
    assert [kind for kind, _ in again] == ["NewEntitlement"]


def test_sync_pages_with_continue(client, db, setup, test_library, monkeypatch):
    from app.services import kobo_service

    device, _ = setup
    shelve(db, device["shelf_id"], add_novel(db, test_library, "Second"))
    monkeypatch.setattr(kobo_service, "SYNC_ITEM_LIMIT", 1)
    first = sync(client, device["token"])
    assert first.headers.get("x-kobo-sync") == "continue"
    assert len(books(first.json())) == 1
    second = sync(client, device["token"], first.headers[SYNC_TOKEN])
    assert "x-kobo-sync" not in second.headers
    assert len(books(second.json())) == 1


def test_metadata_and_download(client, setup):
    device, _ = setup
    [(_, entry)] = books(sync(client, device["token"]).json())
    book_id = entry["BookEntitlement"]["Id"]
    metadata = client.get(f"/kobo/{device['token']}/v1/library/{book_id}/metadata")
    assert metadata.status_code == 200
    assert [item["EntitlementId"] for item in metadata.json()] == [book_id]

    url = metadata.json()[0]["DownloadUrls"][0]["Url"]
    path = url.split("/api", 1)[-1].split("://", 1)[-1]
    path = path[path.index("/kobo/"):]
    download = client.get(path)
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/epub+zip"
    names = zipfile.ZipFile(BytesIO(download.content)).namelist()
    assert "OEBPS/chapter-1.xhtml" in names
    assert int(metadata.json()[0]["DownloadUrls"][0]["Size"]) == len(download.content)
    assert client.get(f"/kobo/{device['token']}/v1/library/00000000-0000-0000-0000-000000000000/metadata").status_code == 404


def test_kepub_when_kepubify_is_available(client, db, setup, tmp_path, monkeypatch):
    fake = tmp_path / "kepubify"
    # Stands in for kepubify: "-o OUT IN" copies IN to OUT.
    fake.write_text('#!/bin/sh\ncp "$3" "$2"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(settings, "NEXUS_KEPUBIFY_PATH", str(fake))
    device, _ = setup
    [(_, entry)] = books(sync(client, device["token"]).json())
    [download] = entry["BookMetadata"]["DownloadUrls"]
    assert download["Format"] == "KEPUB"
    assert "/download/" in download["Url"] and "/kepub?" in download["Url"]
    assert list(tmp_path.rglob("*.kepub.epub"))


def test_progress_round_trip_furthest_position_wins(client, db, setup, test_user, auth_headers):
    device, novel = setup
    token = sync(client, device["token"]).headers[SYNC_TOKEN]
    book_id = db.query(KoboSyncedBook).one().entitlement_id
    state_url = f"/kobo/{device['token']}/v1/library/{book_id}/state"

    # The user explicitly verifies which generated version is installed.
    version=client.get(f"/kobo-devices/{device['id']}/books",headers=auth_headers).json()['items'][0]
    confirmed=client.post(f"/kobo-devices/{device['id']}/books/{book_id}/confirm-version",headers=auth_headers,json={
        'expected_fingerprint':version['fingerprint'],'expected_manifest_epoch':version['manifest_epoch'],
        'expected_manifest_revision':version['manifest_revision'],'reading_run_key':version['reading_run_key']})
    assert confirmed.status_code==200
    # Device -> Nexus (approximate, never content-read proof).
    put = client.put(state_url, json=device_state(book_id, source="OEBPS/chapter-2.xhtml", content=40, overall=45))
    assert put.status_code == 200
    body = put.json()
    assert body["RequestResult"] == "Success"
    assert body["UpdateResults"][0]["CurrentBookmarkResult"] == {"Result": "Success"}
    assert body["UpdateResults"][0]["StatusInfoResult"] == {"Result": "Success"}
    progress = db.query(ReadingProgress).filter_by(user_id=test_user.id, novel_id=novel.id).one()
    assert (progress.chapter_number, round(progress.percent)) == (2, 40)

    [state] = client.get(state_url).json()
    assert state["EntitlementId"] == book_id
    assert state["CurrentBookmark"]["Location"] == {"Value": "kobo.7.2", "Type": "KoboSpan", "Source": "OEBPS/chapter-2.xhtml"}
    assert state["StatusInfo"]["Status"] == "Reading"
    # The device's own position is not echoed back on the next sync.
    assert sync(client, device["token"], token).json() == []

    # Nexus -> device: the web reader moves on to chapter 3.
    chapter3 = db.query(Chapter).filter_by(novel_id=novel.id, chapter_number=3).one()
    from app.services.reading_progress_service import save_reading_progress

    save_reading_progress(db, user_id=test_user.id, chapter=chapter3, position=0, percent=50)
    progress.updated_at = progress.updated_at.replace(year=progress.updated_at.year + 1)
    db.commit()
    [state] = client.get(state_url).json()
    assert state["CurrentBookmark"]["Location"]["Source"] == "OEBPS/chapter-3.xhtml"
    assert state["CurrentBookmark"]["ContentSourceProgressPercent"] == 50
    assert state["CurrentBookmark"]["ProgressPercent"] == pytest.approx(83.33, abs=0.01)
    changed = [item["ChangedReadingState"]["ReadingState"] for item in sync(client, device["token"], token).json() if "ChangedReadingState" in item]
    assert [item["CurrentBookmark"]["Location"]["Source"] for item in changed] == ["OEBPS/chapter-3.xhtml"]

    # An older device position does not move Nexus back.
    client.put(state_url, json=device_state(book_id, source="OEBPS/chapter-1.xhtml", content=10, overall=3))
    db.refresh(progress)
    assert (progress.chapter_number, round(progress.percent)) == (3, 50)

    # Finished on the device: last chapter, 100 %.
    client.put(state_url, json=device_state(book_id, source="OEBPS/chapter-3.xhtml", content=95, overall=99, status="Finished"))
    db.refresh(progress)
    assert (progress.chapter_number, round(progress.percent)) == (3, 100)


def test_malformed_state_is_rejected(client, db, setup):
    device, _ = setup
    sync(client, device["token"])
    book_id = db.query(KoboSyncedBook).one().entitlement_id
    response = client.put(f"/kobo/{device['token']}/v1/library/{book_id}/state", json={"ReadingStates": []})
    assert response.status_code == 400


def test_delete_on_device_takes_the_story_off_the_shelf(client, db, setup):
    device, _ = setup
    token = sync(client, device["token"]).headers[SYNC_TOKEN]
    book_id = db.query(KoboSyncedBook).one().entitlement_id
    assert client.delete(f"/kobo/{device['token']}/v1/library/{book_id}").status_code == 204
    assert db.query(ShelfNovel).count() == 0
    assert books(sync(client, device["token"], token).json()) == []


def test_devices_are_scoped_to_their_user(client, db, setup, test_user):
    device, novel = setup
    sync(client, device["token"])
    book_id = db.query(KoboSyncedBook).one().entitlement_id

    other = User(username="other", password="x")
    db.add(other)
    db.commit()
    other_headers = bearer_headers(other.id, db)
    # Someone else's shelf cannot be chosen, and their device sees nothing of ours.
    mine = db.query(Shelf).filter_by(user_id=test_user.id).one()
    assert client.post("/kobo-devices", json={"shelf_id": mine.id}, headers=other_headers).status_code == 404
    theirs = make_device(client, other_headers)
    shelve(db, theirs["shelf_id"], novel)  # even if our novel lands on their shelf
    assert books(sync(client, theirs["token"]).json()) == []
    assert client.get(f"/kobo/{theirs['token']}/v1/library/{book_id}/state").status_code == 404
    assert client.get(f"/kobo/{theirs['token']}/download/{book_id}/epub").status_code == 404
    assert client.delete(f"/kobo-devices/{device['id']}", headers=other_headers).status_code == 404


def test_shelf_choice(client, db, setup, auth_headers, test_user):
    device, _ = setup
    shelf = Shelf(user_id=test_user.id, name="Commute")
    db.add(shelf)
    db.commit()
    response = client.patch(f"/kobo-devices/{device['id']}", json={"shelf_id": shelf.id}, headers=auth_headers)
    assert response.status_code == 200 and response.json()["shelf_name"] == "Commute"
    assert books(sync(client, device["token"]).json()) == []


def test_unhandled_store_endpoints_answer_locally_without_proxy(client, setup, monkeypatch):
    import httpx

    def refuse(*args, **kwargs):
        raise AssertionError("store proxy used while disabled")

    monkeypatch.setattr(httpx.AsyncClient, "request", refuse)
    device, _ = setup
    token = device["token"]
    assert client.get(f"/kobo/{token}/v1/user/profile").json() == {}
    assert client.post(f"/kobo/{token}/v1/analytics/event", json={"Events": []}).json() == {}
    assert client.get(f"/kobo/{token}/v1/user/loyalty/benefits").json() == {"Benefits": {}}
    tests = client.post(f"/kobo/{token}/v1/analytics/gettests", headers={"x-kobo-userkey": "abc"}).json()
    assert tests == {"Result": "Success", "TestKey": "abc", "Tests": {}}
    auth = client.post(f"/kobo/{token}/v1/auth/device", json={"UserKey": "key-1"}).json()
    assert auth["TokenType"] == "Bearer" and auth["UserKey"] == "key-1"


def test_store_proxy_never_forwards_nexus_credentials(client, setup, monkeypatch):
    import httpx

    seen = {}

    async def fake_request(self, method, url, params=None, headers=None, content=None):
        seen.update(method=method, url=url, headers=headers)
        return httpx.Response(200, json={"Profile": True}, headers={"x-kobo-apitoken": "store"})

    monkeypatch.setattr(httpx.AsyncClient, "request", fake_request)
    monkeypatch.setattr(settings, "NEXUS_KOBO_STORE_PROXY", True)
    device, _ = setup
    response = client.get(
        f"/kobo/{device['token']}/v1/user/profile",
        headers={"Authorization": "Bearer kobo-store-token", "Cookie": "nexus_refresh=secret", "x-real-ip": "1.2.3.4"},
    )
    assert response.json() == {"Profile": True}
    assert seen["url"] == "https://storeapi.kobo.com/v1/user/profile"
    assert device["token"] not in seen["url"]
    lowered = {key.lower(): value for key, value in seen["headers"].items()}
    assert lowered.get("authorization") == "Bearer kobo-store-token"
    assert "cookie" not in lowered and "x-real-ip" not in lowered and "host" not in lowered
