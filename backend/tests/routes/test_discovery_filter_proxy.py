from unittest.mock import AsyncMock, patch

import httpx

from app.services import metadata_client
from tests.auth_helpers import bearer_headers


EMPTY_PAGE = {"data": [], "next_cursor": None, "has_more": False}


def test_discovery_forwards_repeatable_filters_as_lists(client, test_user):
    list_mock = AsyncMock(return_value=EMPTY_PAGE)
    with patch("app.routers.discovery.metadata_client.list_novels_metadata", list_mock):
        response = client.get(
            "/discovery/novels/"
            "?tag=time loop&tag=academy&tag_mode=any"
            "&genre=fantasy&fandom=Naruto&fandom=Bleach"
            "&exclude_tag=character death&exclude_tag=gore"
            "&exclude_fandom=Harry Potter&exclude_genre=horror"
            "&exclude_author=Alice&exclude_text=gore&exclude_text=blood"
            "&language=en&language=French&complete_only=true&hide_inactive=true&crossover=false",
            headers=bearer_headers(test_user.id),
        )

    assert response.status_code == 200
    kwargs = list_mock.await_args.kwargs
    assert kwargs["tag"] == ["time loop", "academy"]
    assert kwargs["tag_mode"] == "any"
    assert kwargs["genre"] == ["fantasy"]
    assert kwargs["fandom"] == ["Naruto", "Bleach"]
    assert kwargs["exclude_tag"] == ["character death", "gore"]
    assert kwargs["exclude_fandom"] == ["Harry Potter"]
    assert kwargs["exclude_genre"] == ["horror"]
    assert kwargs["exclude_author"] == ["Alice"]
    assert kwargs["exclude_text"] == ["gore", "blood"]
    assert kwargs["language"] == ["en", "French"]
    assert kwargs["complete_only"] is True
    assert kwargs["hide_inactive"] is True
    assert kwargs["crossover"] is False


def test_discovery_defaults_leave_new_filters_inactive(client, test_user):
    list_mock = AsyncMock(return_value=EMPTY_PAGE)
    with patch("app.routers.discovery.metadata_client.list_novels_metadata", list_mock):
        response = client.get("/discovery/novels/", headers=bearer_headers(test_user.id))

    assert response.status_code == 200
    kwargs = list_mock.await_args.kwargs
    assert kwargs["tag"] is None
    assert kwargs["exclude_tag"] is None
    assert kwargs["tag_mode"] == "all"
    assert kwargs["complete_only"] is False
    assert kwargs["hide_inactive"] is False
    assert kwargs["crossover"] is None


def test_discovery_rejects_invalid_tag_mode(client, test_user):
    response = client.get("/discovery/novels/?tag_mode=some", headers=bearer_headers(test_user.id))
    assert response.status_code == 422


def test_metadata_client_sends_repeated_query_keys(monkeypatch):
    captured: dict = {}

    async def fake_request(method, path, *, timeout, admin=False, **kwargs):
        captured["path"] = path
        captured["params"] = kwargs["params"]
        return httpx.Response(200, json=EMPTY_PAGE, request=httpx.Request(method, f"http://metadata{path}"))

    monkeypatch.setattr(metadata_client, "_request", fake_request)
    metadata_client.cache.clear()

    import asyncio

    asyncio.run(
        metadata_client.list_novels_metadata(
            tag=["time loop", " ", "academy"],
            tag_mode="any",
            exclude_tag=["gore"],
            exclude_text=[],
            complete_only=True,
            crossover=False,
            limit=20,
        )
    )

    params = captured["params"]
    assert params["tag"] == ["time loop", "academy"]
    assert params["tag_mode"] == "any"
    assert params["exclude_tag"] == ["gore"]
    assert "exclude_text" not in params
    assert params["complete_only"] is True
    assert params["crossover"] is False

    request = httpx.Request("GET", "http://metadata/novels/", params=params)
    query = request.url.query.decode()
    assert query.count("tag=time+loop") == 1 and query.count("tag=academy") == 1
    assert "exclude_tag=gore" in query


def test_metadata_client_cache_key_handles_list_params(monkeypatch):
    calls = []

    async def fake_request(method, path, *, timeout, admin=False, **kwargs):
        calls.append(kwargs["params"])
        return httpx.Response(200, json=EMPTY_PAGE, request=httpx.Request(method, f"http://metadata{path}"))

    monkeypatch.setattr(metadata_client, "_request", fake_request)
    metadata_client.cache.clear()

    import asyncio

    async def run_twice():
        await metadata_client.list_novels_metadata(exclude_tag=["gore"])
        await metadata_client.list_novels_metadata(exclude_tag=["gore"])
        await metadata_client.list_novels_metadata(exclude_tag=["blood"])

    asyncio.run(run_twice())
    # The identical second call is served from cache; a different list is not.
    assert len(calls) == 2
    metadata_client.cache.clear()
