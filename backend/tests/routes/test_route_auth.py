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
    # KOReader registration is refused: accounts are created in the web UI.
    ("POST", "/kosync/users/create"),
    ("GET", "/notifications/vapid-public-key"),
    # Authenticated by the shared webhook secret instead of a user session.
    ("POST", "/novel/internal/metadata-events"),
    ("GET", "/opds/opensearch.xml"),
    # Authenticated by the random feed token in the path (no session).
    ("GET", "/feeds/{token_file}"),
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
