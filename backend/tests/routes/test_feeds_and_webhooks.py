import hashlib
import hmac
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from xml.etree import ElementTree as ET

import pytest

from app.models.library import Library
from app.models.novel import Novel
from app.models.personal_feed import UserFeedToken
from app.models.update_event import NovelUpdateEvent
from app.models.webhook import Webhook, WebhookDelivery
from app.services import webhook_delivery
from app.services.notification_crypto import decrypt_url, encrypt_url
from config.settings import settings

ATOM = "{http://www.w3.org/2005/Atom}"
PUBLIC_URL = "https://hooks.example.test/nexus"


@pytest.fixture
def library(db, test_user):
    library = Library(name="Shelf", user_id=test_user.id)
    db.add(library)
    db.commit()
    return library


@pytest.fixture
def novel(db, library):
    novel = Novel(
        title="Moon & Stars",
        library_id=library.id,
        metadata_id=4242,
        url="https://www.royalroad.com/fiction/4242",
        novel_site="royalroad",
    )
    db.add(novel)
    db.commit()
    return novel


def add_event(db, user, novel, chapters=3, first=10, last=12, released=True):
    event = NovelUpdateEvent(
        user_id=user.id,
        novel_id=novel.id,
        event_type="new_chapters",
        chapter_count=chapters,
        first_chapter_number=first,
        last_chapter_number=last,
        message=f"{chapters} new chapter(s) available",
        notified_at=datetime.now(UTC).replace(tzinfo=None) if released else None,
    )
    db.add(event)
    db.commit()
    return event


def rotate_token(client, auth_headers) -> str:
    response = client.post("/personal-feed/token", headers=auth_headers)
    assert response.status_code == 201
    return response.json()["feed_url"].rsplit("/feeds/", 1)[1].removesuffix(".atom")


# ---- personal feed -------------------------------------------------------


def test_feed_serves_latest_updates_as_valid_atom_without_session(client, auth_headers, db, test_user, novel):
    add_event(db, test_user, novel)
    token = rotate_token(client, auth_headers)

    response = client.get(f"/feeds/{token}.atom")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/atom+xml")
    root = ET.fromstring(response.text)  # raises on malformed XML
    assert root.tag == f"{ATOM}feed"
    entry = root.find(f"{ATOM}entry")
    assert entry.find(f"{ATOM}title").text == "Moon & Stars — 3 new chapters"
    assert entry.find(f"{ATOM}link").get("href").endswith("/story/4242")
    assert entry.find(f"{ATOM}id").text.startswith("urn:nexus:update:")
    assert entry.find(f"{ATOM}updated").text.endswith("Z")
    assert root.find(f"{ATOM}updated") is not None


def test_feed_is_limited_to_fifty_latest_events_of_that_user(client, auth_headers, db, test_user, novel):
    for _ in range(55):
        add_event(db, test_user, novel)
    token = rotate_token(client, auth_headers)
    root = ET.fromstring(client.get(f"/feeds/{token}.atom").text)
    assert len(root.findall(f"{ATOM}entry")) == 50


def test_rotating_the_token_invalidates_the_old_url(client, auth_headers):
    old = rotate_token(client, auth_headers)
    new = rotate_token(client, auth_headers)
    assert old != new
    assert client.get(f"/feeds/{old}.atom").status_code == 404
    assert client.get(f"/feeds/{new}.atom").status_code == 200


def test_only_a_hash_of_the_token_is_stored(client, auth_headers, db):
    token = rotate_token(client, auth_headers)
    row = db.query(UserFeedToken).one()
    assert row.token_hash == hashlib.sha256(token.encode()).hexdigest()
    assert token not in row.token_hash


def test_revoked_token_stops_working(client, auth_headers):
    token = rotate_token(client, auth_headers)
    assert client.delete("/personal-feed/token", headers=auth_headers).status_code == 204
    assert client.get(f"/feeds/{token}.atom").status_code == 404
    assert client.get("/personal-feed", headers=auth_headers).json()["active"] is False


def test_bad_feed_requests_are_404_and_rate_limited(client, auth_headers):
    rotate_token(client, auth_headers)
    assert client.get("/feeds/not-a-token.xml").status_code == 404
    statuses = [client.get("/feeds/wrong-token.atom").status_code for _ in range(40)]
    assert 404 in statuses
    assert statuses[-1] == 429


# ---- webhook API ---------------------------------------------------------


def test_webhook_crud_never_returns_the_secret(client, auth_headers, db):
    created = client.post(
        "/webhooks",
        json={"url": PUBLIC_URL, "secret": "s3cret", "event_types": ["new_chapters"]},
        headers=auth_headers,
    )
    assert created.status_code == 201
    body = created.json()
    assert body["has_secret"] is True
    assert "s3cret" not in created.text
    assert body["url_hint"] == "https://hooks.example.test/..."
    stored = db.query(Webhook).one()
    assert stored.secret_encrypted and decrypt_url(stored.secret_encrypted) == "s3cret"

    updated = client.patch(f"/webhooks/{body['id']}", json={"enabled": False}, headers=auth_headers)
    assert updated.json()["enabled"] is False
    assert len(client.get("/webhooks", headers=auth_headers).json()) == 1
    assert client.delete(f"/webhooks/{body['id']}", headers=auth_headers).status_code == 204
    assert client.get("/webhooks", headers=auth_headers).json() == []


@pytest.mark.parametrize(
    "url",
    ["ftp://hooks.example.test/x", "https://127.0.0.1/hook", "http://10.0.0.5:8080/hook"],
)
def test_webhook_refuses_non_public_targets(client, auth_headers, monkeypatch, url):
    monkeypatch.setattr(settings, "NOTIFY_ALLOW_PRIVATE_HOSTS", False)
    response = client.post("/webhooks", json={"url": url}, headers=auth_headers)
    assert response.status_code == 422


def test_webhook_rejects_unknown_event_type(client, auth_headers):
    response = client.post("/webhooks", json={"url": PUBLIC_URL, "event_types": ["nope"]}, headers=auth_headers)
    assert response.status_code == 422


def test_webhooks_belong_to_their_owner(client, auth_headers, db, test_user):
    created = client.post("/webhooks", json={"url": PUBLIC_URL}, headers=auth_headers).json()
    from app.models.user import User

    other = User(username="other", password="x")
    db.add(other)
    db.commit()
    from tests.auth_helpers import bearer_headers

    other_headers = bearer_headers(other.id, db)
    assert client.get("/webhooks", headers=other_headers).json() == []
    assert client.delete(f"/webhooks/{created['id']}", headers=other_headers).status_code == 404


# ---- webhook delivery ----------------------------------------------------


@pytest.fixture
def posts(monkeypatch):
    calls = SimpleNamespace(items=[], status=200)

    def fake_post(url, content, headers, timeout, follow_redirects):
        calls.items.append(SimpleNamespace(url=url, body=content, headers=headers, timeout=timeout, redirects=follow_redirects))
        return SimpleNamespace(status_code=calls.status)

    monkeypatch.setattr(webhook_delivery.httpx, "post", fake_post)
    return calls


def make_hook(db, user, url=PUBLIC_URL, secret="topsecret", **extra):
    hook = Webhook(
        user_id=user.id,
        url_encrypted=encrypt_url(url),
        url_hint="",
        secret_encrypted=encrypt_url(secret) if secret else None,
        event_types=["new_chapters"],
        created_at=datetime(2020, 1, 1),
        **extra,
    )
    db.add(hook)
    db.commit()
    return hook


def test_payload_is_signed_and_has_the_documented_shape(db, test_user, novel, posts):
    make_hook(db, test_user)
    add_event(db, test_user, novel)

    assert webhook_delivery.deliver_due_webhooks(db) == 1

    sent = posts.items[0]
    assert sent.timeout == 10 and sent.redirects is False
    expected = "sha256=" + hmac.new(b"topsecret", sent.body, hashlib.sha256).hexdigest()
    assert sent.headers["X-Nexus-Signature"] == expected
    payload = json.loads(sent.body)
    assert payload["event"] == "new_chapters"
    assert payload["story"] == {
        "title": "Moon & Stars",
        "url": "https://www.royalroad.com/fiction/4242",
        "site": "royalroad",
    }
    assert payload["chapters"] == {"count": 3, "first": 10, "last": 12}
    assert payload["created_at"].endswith("Z")


def test_unsigned_webhook_has_no_signature_header(db, test_user, novel, posts):
    make_hook(db, test_user, secret=None)
    add_event(db, test_user, novel)
    webhook_delivery.deliver_due_webhooks(db)
    assert "X-Nexus-Signature" not in posts.items[0].headers


def test_unreleased_events_are_not_sent(db, test_user, novel, posts):
    make_hook(db, test_user)
    add_event(db, test_user, novel, released=False)
    assert webhook_delivery.deliver_due_webhooks(db) == 0
    assert posts.items == []


def test_event_is_posted_once_per_webhook(db, test_user, novel, posts):
    make_hook(db, test_user)
    add_event(db, test_user, novel)
    webhook_delivery.deliver_due_webhooks(db)
    webhook_delivery.deliver_due_webhooks(db)
    assert len(posts.items) == 1
    assert db.query(WebhookDelivery).count() == 1


def test_private_target_is_refused_without_a_request(db, test_user, novel, posts, monkeypatch):
    monkeypatch.setattr(settings, "NOTIFY_ALLOW_PRIVATE_HOSTS", False)
    hook = make_hook(db, test_user, url="http://127.0.0.1:9000/hook")
    add_event(db, test_user, novel)
    webhook_delivery.deliver_due_webhooks(db)
    assert posts.items == []
    db.refresh(hook)
    assert hook.last_error and "not a public" in hook.last_error
    assert hook.consecutive_failures == 1


def test_webhook_is_disabled_after_ten_consecutive_failures(db, test_user, novel, posts):
    hook = make_hook(db, test_user)
    posts.status = 500
    for _ in range(10):
        add_event(db, test_user, novel)
    webhook_delivery.deliver_due_webhooks(db)
    db.refresh(hook)
    assert len(posts.items) == 10
    assert hook.enabled is False
    assert hook.consecutive_failures == 10
    assert hook.last_status_code == 500 and hook.last_error == "HTTP 500"


def test_success_resets_the_failure_count(db, test_user, novel, posts):
    hook = make_hook(db, test_user, consecutive_failures=9)
    add_event(db, test_user, novel)
    webhook_delivery.deliver_due_webhooks(db)
    db.refresh(hook)
    assert hook.consecutive_failures == 0 and hook.enabled is True and hook.last_error is None


def test_test_send_reports_the_result(client, auth_headers, db, test_user, posts):
    hook = make_hook(db, test_user)
    result = client.post(f"/webhooks/{hook.id}/test", headers=auth_headers)
    assert result.status_code == 200
    assert result.json() == {"ok": True, "status_code": 200, "error": None}
    assert json.loads(posts.items[0].body)["event"] == "test"
