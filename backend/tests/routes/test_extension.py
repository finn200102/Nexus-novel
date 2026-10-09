import base64

import pytest

from app.auth.passwords import hash_password
from app.models.library import Library
from app.services import app_password_service

ACCOUNT_PASSWORD = "account-pass-123"
STORY_URL = "https://www.fanfiction.net/s/123456/1/Some-Story"
ORIGIN = "chrome-extension://abcdefghijklmnopabcdefghijklmnop"


@pytest.fixture
def reader(db, test_user):
    test_user.password = hash_password(ACCOUNT_PASSWORD)
    db.commit()
    return test_user


@pytest.fixture
def library(db, reader):
    library = Library(name="Shelf", user_id=reader.id)
    db.add(library)
    db.commit()
    return library


def basic(username: str, password: str) -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


def make_app_password(client, auth_headers, scope: str) -> str:
    response = client.post("/app-passwords", json={"label": "Browser", "scope": scope}, headers=auth_headers)
    assert response.status_code == 201
    return response.json()["secret"]


def test_extension_scope_can_be_created_and_listed_as_scope(client, auth_headers):
    secret = make_app_password(client, auth_headers, "extension")
    assert secret
    rows = client.get("/app-passwords", headers=auth_headers).json()
    assert any(row["scope"] == "extension" for row in rows)


def test_extension_routes_require_basic_auth_with_a_challenge(client):
    response = client.get("/ext/libraries")
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")


def test_account_password_is_not_accepted_by_extension_routes(client, reader):
    response = client.get("/ext/libraries", headers=basic(reader.username, ACCOUNT_PASSWORD))
    assert response.status_code == 401


def test_opds_and_kosync_app_passwords_do_not_work_for_extension(client, auth_headers, reader):
    opds_secret = make_app_password(client, auth_headers, "opds")
    kosync_secret = make_app_password(client, auth_headers, "kosync")
    assert client.get("/ext/libraries", headers=basic(reader.username, opds_secret)).status_code == 401
    assert client.get("/ext/libraries", headers=basic(reader.username, kosync_secret)).status_code == 401


def test_extension_app_password_lists_own_libraries_only(client, auth_headers, reader, library, db):
    other = Library(name="Someone else", user_id=reader.id + 1000)
    db.add(other)
    db.commit()
    secret = make_app_password(client, auth_headers, "extension")
    response = client.get("/ext/libraries", headers=basic(reader.username, secret))
    assert response.status_code == 200
    assert response.json() == [{"id": library.id, "name": "Shelf"}]


def test_add_queues_a_story_job_for_the_url(client, auth_headers, reader, library):
    secret = make_app_password(client, auth_headers, "extension")
    response = client.post(
        "/ext/add",
        json={"url": f"  {STORY_URL}  ", "library_id": library.id},
        headers=basic(reader.username, secret),
    )
    assert response.status_code == 202
    body = response.json()
    assert body["library_id"] == library.id
    assert body["source"] == "url_list"
    assert body["total_items"] == 1
    assert body["items"][0]["url"] == STORY_URL


def test_add_rejects_text_without_a_url(client, auth_headers, reader, library):
    secret = make_app_password(client, auth_headers, "extension")
    response = client.post(
        "/ext/add", json={"url": "not a link", "library_id": library.id}, headers=basic(reader.username, secret)
    )
    assert response.status_code == 422


def test_add_to_another_users_library_is_refused(client, auth_headers, reader, db):
    foreign = Library(name="Foreign", user_id=reader.id + 1000)
    db.add(foreign)
    db.commit()
    secret = make_app_password(client, auth_headers, "extension")
    response = client.post(
        "/ext/add", json={"url": STORY_URL, "library_id": foreign.id}, headers=basic(reader.username, secret)
    )
    assert response.status_code in (403, 404)


def test_revoked_extension_password_stops_working(client, auth_headers, reader, library):
    secret = make_app_password(client, auth_headers, "extension")
    row_id = next(row["id"] for row in client.get("/app-passwords", headers=auth_headers).json() if row["scope"] == "extension")
    assert client.delete(f"/app-passwords/{row_id}", headers=auth_headers).status_code == 204
    assert client.get("/ext/libraries", headers=basic(reader.username, secret)).status_code == 401


def test_cors_allows_extension_origins_on_ext_routes_only(client, auth_headers, reader, library):
    secret = make_app_password(client, auth_headers, "extension")
    response = client.get("/ext/libraries", headers={**basic(reader.username, secret), "Origin": ORIGIN})
    assert response.headers.get("access-control-allow-origin") == ORIGIN

    preflight = client.options(
        "/ext/add",
        headers={
            "Origin": "moz-extension://1234-abcd",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert preflight.status_code == 204
    assert preflight.headers["access-control-allow-origin"] == "moz-extension://1234-abcd"
    assert "Authorization" in preflight.headers["access-control-allow-headers"]


def test_cors_is_not_extended_to_other_api_paths(client):
    response = client.get("/novels/", headers={"Origin": ORIGIN})
    assert "access-control-allow-origin" not in response.headers


def test_unknown_origin_gets_no_cors_on_ext_routes(client, auth_headers, reader, library):
    secret = make_app_password(client, auth_headers, "extension")
    response = client.get("/ext/libraries", headers={**basic(reader.username, secret), "Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_extension_auth_is_rate_limited_per_user(client, reader):
    limit = app_password_service.APP_AUTH_FAILURES_PER_USER.max_attempts
    statuses = [client.get("/ext/libraries", headers=basic(reader.username, "wrong")).status_code for _ in range(limit + 2)]
    assert statuses[-1] == 429
