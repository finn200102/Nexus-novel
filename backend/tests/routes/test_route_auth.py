"""Every API route requires authentication unless it is listed here.

Guards against new endpoints that forget their auth dependency (the audio
provider check endpoints were reachable anonymously and fetched arbitrary
URLs from the server).
"""
import re

from fastapi.routing import APIRoute

from app.main import app

PUBLIC = {
    ("GET", "/"),
    ("GET", "/health"),
    ("GET", "/audio/providers"),
    ("GET", "/auth/config"),
    ("POST", "/auth/signup"),
    ("POST", "/auth/login"),
    ("POST", "/auth/refresh"),
    ("POST", "/auth/logout"),
    ("POST", "/auth/password-reset"),
    # Single sign-on: the provider authenticates; the callback checks the
    # signed flow cookie and the ID token.
    ("GET", "/auth/oidc/login"),
    ("GET", "/auth/oidc/callback"),
    # KOReader registration is refused: accounts are created in the web UI.
    ("POST", "/kosync/users/create"),
    ("GET", "/notifications/vapid-public-key"),
    # Authenticated by the shared webhook secret instead of a user session.
    ("POST", "/novel/internal/metadata-events"),
    ("GET", "/opds/opensearch.xml"),
    # Authenticated by the random feed token in the path (no session).
    ("GET", "/feeds/{token_file}"),
    # Story-scoped podcast credentials replace session auth for subscribed apps.
    ("GET", "/podcasts/{token}/feed.xml"),
    ("GET", "/podcasts/{token}/audio/{job_id}"),
    ("GET", "/podcasts/{token}/audio/{job_id}.mp3"),
}


def _routes():
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods - {"HEAD", "OPTIONS"}:
            yield method, route.path


def test_routes_reject_anonymous_requests(client):
    open_routes = []
    for method, path in _routes():
        if (method, path) in PUBLIC:
            continue
        url = re.sub(r"\{[^}]+\}", "1", path)
        response = client.request(method, url, json={})
        if response.status_code not in (401, 403):
            open_routes.append(f"{method} {path} -> {response.status_code}")
    assert open_routes == []


def test_public_list_has_no_stale_entries():
    assert PUBLIC - set(_routes()) == set()


def test_private_api_responses_are_not_reusable_by_the_browser_http_cache(client, auth_headers):
    response = client.get("/library/", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert {"Authorization", "Cookie"}.issubset(set(response.headers["vary"].split(", ")))
