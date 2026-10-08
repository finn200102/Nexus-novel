"""Live site search through the metadata server, merged with catalog hits."""

from unittest.mock import AsyncMock

from app.models.blocklist import BlocklistEntry

RR_URL = "https://www.royalroad.com/fiction/1/mother-of-learning"


def _live(site, results=None, error=None):
    return {"site": site, "page": 1, "results": results or [], "error": error}


def test_live_search_merges_local_hits_and_reports_site_errors(client, db, test_user, auth_headers, monkeypatch):
    db.add(BlocklistEntry(user_id=test_user.id, kind="author", value="Blocked Author"))
    db.commit()
    answers = {
        "royalroad": _live("royalroad", [
            {"metadata_id": 5, "url": RR_URL + "/", "title": "Mother of Learning", "author": "nobody103"},
            {"metadata_id": 6, "url": "https://www.royalroad.com/fiction/2/x", "title": "Other", "author": "Blocked Author"},
        ]),
        "fanfiction": _live("fanfiction", error={"code": "rate_limited", "message": "HTTP 429 (Retry-After: 30)"}),
    }
    calls = []

    async def live_listing(kind, params):
        calls.append((kind, params))
        return answers[params["site"]]

    monkeypatch.setattr("app.services.metadata_client.live_listing", live_listing)
    monkeypatch.setattr(
        "app.services.metadata_client.list_novels_metadata",
        AsyncMock(return_value={"data": [{"id": 5, "source_url": RR_URL, "title": "Mother of Learning"}]}),
    )

    response = client.get(
        "/discovery/live", params={"q": "mother", "sites": ["royalroad", "fanfiction"]}, headers=auth_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert [(row["title"], row["sources"]) for row in body["results"]] == [("Mother of Learning", ["live", "local"])]
    assert body["errors"] == [{"site": "fanfiction", "code": "rate_limited", "message": "HTTP 429 (Retry-After: 30)"}]
    assert {params["site"] for _, params in calls} == {"royalroad", "fanfiction"}


def test_live_browse_applies_blocklist(client, db, test_user, auth_headers, monkeypatch):
    db.add(BlocklistEntry(user_id=test_user.id, kind="tag", value="Harem"))
    db.commit()

    async def live_listing(kind, params):
        assert (kind, params["feed"]) == ("browse", "rising-stars")
        return _live("royalroad", [
            {"metadata_id": 1, "url": "https://www.royalroad.com/fiction/1", "title": "A", "tags": ["Harem"]},
            {"metadata_id": 2, "url": "https://www.royalroad.com/fiction/2", "title": "B", "tags": ["LitRPG"]},
        ])

    monkeypatch.setattr("app.services.metadata_client.live_listing", live_listing)
    body = client.get("/discovery/live/browse", params={"site": "royalroad", "feed": "rising-stars"}, headers=auth_headers).json()
    assert [row["title"] for row in body["results"]] == ["B"]
    assert body["errors"] == []
