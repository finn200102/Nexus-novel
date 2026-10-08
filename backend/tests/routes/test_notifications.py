from unittest.mock import patch

from config.settings import settings
from app.models.notification import NotificationChannel, PushSubscription
from app.models.user import User
from tests import auth_helpers

ENDPOINT = "https://push.example.test/send/abc123"
KEYS = {"p256dh": "BPublicKeyValue", "auth": "AuthSecretValue"}


def other_user_headers(db, name="other"):
    user = User(username=name, password="x")
    db.add(user)
    db.commit()
    return auth_helpers.bearer_headers(user.id, db)


def test_vapid_public_key_is_exposed_without_auth(client):
    response = client.get("/notifications/vapid-public-key")

    assert response.status_code == 200
    assert response.json() == {"public_key": settings.VAPID_PUBLIC_KEY}
    assert settings.VAPID_PRIVATE_KEY not in response.text


def test_notification_endpoints_require_a_session(client):
    assert client.get("/notifications/channels").status_code == 401
    assert client.get("/notifications/push/subscriptions").status_code == 401


def test_subscribe_is_idempotent_per_endpoint(client, auth_headers, db):
    body = {"endpoint": ENDPOINT, "keys": KEYS}

    first = client.post("/notifications/push/subscriptions", json=body, headers={**auth_headers, "User-Agent": "Phone"})
    second = client.post("/notifications/push/subscriptions", json=body, headers=auth_headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["user_agent"] == "Phone"
    assert db.query(PushSubscription).count() == 1
    listed = client.get("/notifications/push/subscriptions", headers=auth_headers).json()
    assert [row["id"] for row in listed] == [first.json()["id"]]
    assert "endpoint" not in listed[0]


def test_subscribe_rejects_plain_http_endpoints(client, auth_headers):
    response = client.post(
        "/notifications/push/subscriptions",
        json={"endpoint": "http://push.example.test/abc", "keys": KEYS},
        headers=auth_headers,
    )

    assert response.status_code == 422


def test_unsubscribe_and_delete_only_touch_own_devices(client, auth_headers, db):
    created = client.post("/notifications/push/subscriptions", json={"endpoint": ENDPOINT, "keys": KEYS}, headers=auth_headers).json()
    intruder = other_user_headers(db)

    assert client.delete(f"/notifications/push/subscriptions/{created['id']}", headers=intruder).status_code == 404
    assert client.post("/notifications/push/unsubscribe", json={"endpoint": ENDPOINT}, headers=intruder).json() == {"removed": 0}
    assert client.post("/notifications/push/unsubscribe", json={"endpoint": ENDPOINT}, headers=auth_headers).json() == {"removed": 1}
    assert db.query(PushSubscription).count() == 0


def test_channel_url_is_encrypted_and_never_returned(client, auth_headers, db):
    secret_url = "ntfy://ntfy.sh/topic-secret-123"

    response = client.post(
        "/notifications/channels",
        json={"url": secret_url, "label": "My phone"},
        headers=auth_headers,
    )

    assert response.status_code == 201
    body = response.json()
    assert body["label"] == "My phone"
    assert body["url_hint"] == "ntfy://ntfy.sh/..."
    assert "topic-secret-123" not in response.text
    listed = client.get("/notifications/channels", headers=auth_headers)
    assert "topic-secret-123" not in listed.text
    stored = db.query(NotificationChannel).one()
    assert "topic-secret-123" not in stored.url_encrypted


def test_invalid_channel_url_is_refused_without_echoing_it(client, auth_headers):
    response = client.post("/notifications/channels", json={"url": "not-a-real-scheme://token-abc"}, headers=auth_headers)

    assert response.status_code == 422
    assert "token-abc" not in response.text


def test_channel_can_be_disabled_relabelled_and_deleted(client, auth_headers, db):
    channel = client.post("/notifications/channels", json={"url": "json://notify.example.test:9/"}, headers=auth_headers).json()

    patched = client.patch(f"/notifications/channels/{channel['id']}", json={"enabled": False, "label": "Server"}, headers=auth_headers)

    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
    assert patched.json()["label"] == "Server"
    assert client.delete(f"/notifications/channels/{channel['id']}", headers=auth_headers).status_code == 204
    assert db.query(NotificationChannel).count() == 0


def test_other_users_channels_are_not_visible(client, auth_headers, db):
    channel = client.post("/notifications/channels", json={"url": "json://notify.example.test:9/"}, headers=auth_headers).json()
    intruder = other_user_headers(db)

    assert client.patch(f"/notifications/channels/{channel['id']}", json={"enabled": False}, headers=intruder).status_code == 404
    assert client.delete(f"/notifications/channels/{channel['id']}", headers=intruder).status_code == 404
    assert client.get("/notifications/channels", headers=intruder).json() == []


def test_test_endpoint_returns_a_result_per_channel(client, auth_headers):
    client.post("/notifications/channels", json={"url": "json://notify.example.test:9/", "label": "Dead"}, headers=auth_headers)
    client.post("/notifications/channels", json={"url": "json://localhost:10/", "label": "Off", "enabled": False}, headers=auth_headers)

    with patch("app.services.notification_delivery.send_apprise", return_value=False) as send:
        response = client.post("/notifications/test", headers=auth_headers)

    assert response.status_code == 200
    channels = response.json()["channels"]
    assert [row["label"] for row in channels] == ["Dead"]
    assert channels[0]["ok"] is False
    assert channels[0]["error"] == "Delivery failed"
    assert channels[0]["url_hint"] == "json://notify.example.test:9/..."
    send.assert_called_once()
    assert send.call_args.args[0] == "json://notify.example.test:9/"


def test_test_endpoint_survives_a_raising_channel(client, auth_headers):
    client.post("/notifications/channels", json={"url": "json://notify.example.test:9/"}, headers=auth_headers)

    with patch("app.services.notification_delivery.send_apprise", side_effect=OSError("refused")):
        response = client.post("/notifications/test", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["channels"][0]["error"] == "Delivery raised an error"


def test_targets_on_private_networks_are_refused(client, auth_headers, monkeypatch):
    for url in ("json://localhost:9/", "json://127.0.0.1/", "ntfys://10.0.0.5/topic", "form://169.254.169.254/"):
        response = client.post("/notifications/channels", json={"url": url}, headers=auth_headers)
        assert response.status_code == 422, url
    response = client.post(
        "/notifications/push/subscriptions",
        json={"endpoint": "https://192.168.1.10/push/abc", "keys": KEYS},
        headers=auth_headers,
    )
    assert response.status_code == 422

    from config.settings import settings

    monkeypatch.setattr(settings, "NOTIFY_ALLOW_PRIVATE_HOSTS", True)
    response = client.post("/notifications/channels", json={"url": "ntfys://10.0.0.5/topic"}, headers=auth_headers)
    assert response.status_code == 201


def test_delivery_rechecks_the_destination(monkeypatch):
    import pytest

    from app.services import notification_delivery
    from app.services.outbound_url import BlockedDestination

    with pytest.raises(BlockedDestination):
        notification_delivery.send_apprise("json://127.0.0.1:9/", "t", "b")
