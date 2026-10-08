import os
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from dotenv import load_dotenv
from pywebpush import WebPushException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models  # noqa: F401  (registers every mapper)
from app.models.base import BaseModel
from app.models.follow import UserNovelFollow
from app.models.library import Library
from app.models.novel import Novel
from app.models.notification import NotificationChannel, PushSubscription
from app.models.update_event import NovelUpdateEvent
from app.models.user import User
from app.services import notification_delivery
from app.services.notification_crypto import decrypt_url, encrypt_url, url_hint
from app.services.notification_delivery import deliver_due_notifications, send_test

load_dotenv()

engine = create_engine(os.environ["DATABASE_URL"])
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db():
    BaseModel.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        BaseModel.metadata.drop_all(bind=engine)


@pytest.fixture
def sent(monkeypatch):
    """Record every push and Apprise call instead of using the network."""
    calls = SimpleNamespace(push=[], apprise=[], push_error=None, apprise_result=True)

    def fake_push(subscription, payload):
        calls.push.append((subscription.endpoint, payload))
        if calls.push_error is not None:
            raise calls.push_error

    def fake_apprise(url, title, body):
        calls.apprise.append((url, title, body))
        return calls.apprise_result

    monkeypatch.setattr(notification_delivery, "send_web_push", fake_push)
    monkeypatch.setattr(notification_delivery, "send_apprise", fake_apprise)
    return calls


def make_user(db, name="reader"):
    user = User(username=name, password="x")
    db.add(user)
    db.commit()
    return user


def make_novel(db, user, title="Story", url=None):
    library = db.query(Library).filter(Library.user_id == user.id).first()
    if library is None:
        library = Library(name="Main", user_id=user.id)
        db.add(library)
        db.commit()
    novel = Novel(title=title, library_id=library.id, url=url or f"https://example.test/{title}")
    db.add(novel)
    db.commit()
    return novel


def follow(db, user, novel, policy="immediate"):
    db.add(UserNovelFollow(user_id=user.id, novel_id=novel.id, notification_policy=policy, notification_count=1))
    db.commit()


def event(db, user, novel, chapters=(1,), visible=True, message="New chapters"):
    row = NovelUpdateEvent(
        user_id=user.id,
        novel_id=novel.id,
        event_type="chapters_added",
        chapter_count=len(chapters),
        first_chapter_number=min(chapters),
        last_chapter_number=max(chapters),
        message=message,
        details={},
        notification_visible=visible,
        created_at=datetime.now(UTC).replace(tzinfo=None),
    )
    db.add(row)
    db.commit()
    return row


def add_push(db, user, endpoint="https://push.example.test/abc"):
    row = PushSubscription(user_id=user.id, endpoint=endpoint, p256dh="p", auth="a", failure_count=0)
    db.add(row)
    db.commit()
    return row


def add_channel(db, user, url="ntfy://ntfy.sh/topic-secret-123", enabled=True):
    row = NotificationChannel(
        user_id=user.id,
        url_encrypted=encrypt_url(url),
        url_hint=url_hint(url),
        label="phone",
        enabled=enabled,
    )
    db.add(row)
    db.commit()
    return row


def test_immediate_event_goes_to_push_and_channels(db, sent):
    user = make_user(db)
    novel = make_novel(db, user, "Dungeon Story")
    follow(db, user, novel)
    push = add_push(db, user)
    channel = add_channel(db, user)
    update = event(db, user, novel, chapters=(10, 11, 12))

    report = deliver_due_notifications(db)

    assert report.events == 1
    assert len(sent.push) == 1
    endpoint, payload = sent.push[0]
    assert endpoint == push.endpoint
    assert payload["title"] == "Dungeon Story"
    assert payload["body"] == "3 new chapters (10–12)"
    assert payload["tag"] == f"novel-{novel.id}"
    assert payload["url"] == f"/library/{novel.library_id}/novels/{novel.id}"
    assert sent.apprise == [("ntfy://ntfy.sh/topic-secret-123", "Dungeon Story", "3 new chapters (10–12)")]
    db.refresh(update)
    db.refresh(push)
    db.refresh(channel)
    assert update.notified_at is not None
    assert push.last_success_at is not None
    assert channel.last_error is None


def test_released_event_is_never_sent_twice(db, sent):
    user = make_user(db)
    novel = make_novel(db, user)
    follow(db, user, novel)
    add_push(db, user)
    event(db, user, novel)

    deliver_due_notifications(db)
    second = deliver_due_notifications(db)

    assert second.events == 0
    assert len(sent.push) == 1


def test_failed_send_still_counts_as_delivered(db, sent):
    user = make_user(db)
    novel = make_novel(db, user)
    follow(db, user, novel)
    sent.apprise_result = False
    channel = add_channel(db, user)
    update = event(db, user, novel)

    deliver_due_notifications(db)

    db.refresh(channel)
    db.refresh(update)
    assert channel.last_error == "Delivery failed"
    assert update.notified_at is not None
    assert len(sent.apprise) == 1


def test_hidden_digest_event_waits_for_release(db, sent):
    user = make_user(db)
    novel = make_novel(db, user)
    follow(db, user, novel, policy="daily_digest")
    add_push(db, user)
    update = event(db, user, novel, visible=False)

    assert deliver_due_notifications(db).events == 0
    assert sent.push == []

    update.notification_visible = True
    db.commit()
    deliver_due_notifications(db)

    assert len(sent.push) == 1


def test_digest_is_one_message_listing_each_story(db, sent):
    user = make_user(db)
    first = make_novel(db, user, "Alpha")
    second = make_novel(db, user, "Beta")
    follow(db, user, first, policy="daily_digest")
    follow(db, user, second, policy="weekly_digest")
    add_push(db, user)
    event(db, user, first, chapters=(4, 5, 6))
    event(db, user, second, chapters=(9,))

    deliver_due_notifications(db)

    assert len(sent.push) == 1
    payload = sent.push[0][1]
    assert payload["title"] == "2 stories updated"
    assert payload["tag"] == "nexus-digest"
    assert payload["url"] == "/activity"
    assert "Alpha: 3 new" in payload["body"]
    assert "Beta: 1 new" in payload["body"]


def test_disabled_channel_is_skipped(db, sent):
    user = make_user(db)
    novel = make_novel(db, user)
    follow(db, user, novel)
    add_channel(db, user, enabled=False)
    event(db, user, novel)

    deliver_due_notifications(db)

    assert sent.apprise == []


@pytest.mark.parametrize("status", [404, 410])
def test_gone_push_subscription_is_deleted(db, sent, status):
    user = make_user(db)
    novel = make_novel(db, user)
    follow(db, user, novel)
    add_push(db, user)
    sent.push_error = WebPushException("gone", response=SimpleNamespace(status_code=status, headers={}))
    event(db, user, novel)

    report = deliver_due_notifications(db)

    assert report.push_removed == 1
    assert db.query(PushSubscription).count() == 0


def test_server_error_keeps_subscription_and_counts_failure(db, sent):
    user = make_user(db)
    novel = make_novel(db, user)
    follow(db, user, novel)
    push = add_push(db, user)
    sent.push_error = WebPushException("boom", response=SimpleNamespace(status_code=500, headers={}))
    event(db, user, novel)

    report = deliver_due_notifications(db)

    db.refresh(push)
    assert report.push_failed == 1
    assert push.failure_count == 1
    assert db.query(PushSubscription).count() == 1


def test_apprise_exception_is_recorded_without_the_url(db, sent, monkeypatch):
    user = make_user(db)
    novel = make_novel(db, user)
    follow(db, user, novel)
    channel = add_channel(db, user, url="json://user:hunter2@example.test/hook")

    def explode(url, title, body):
        raise RuntimeError(f"failed for {url}")

    monkeypatch.setattr(notification_delivery, "send_apprise", explode)
    event(db, user, novel)

    deliver_due_notifications(db)

    db.refresh(channel)
    assert channel.last_error == "Delivery raised an error"
    assert "hunter2" not in channel.last_error


def test_send_test_reports_each_channel_and_device(db, sent):
    user = make_user(db)
    add_push(db, user)
    good = add_channel(db, user, url="json://localhost:9/")
    sent.apprise_result = False

    result = send_test(db, user)

    assert result["push"] == {"sent": 1, "failed": 0, "removed": 0}
    assert result["channels"] == [
        {"id": good.id, "label": "phone", "url_hint": good.url_hint, "ok": False, "error": "Delivery failed"}
    ]
    assert "ntfy" not in str(result)


def test_apprise_url_round_trips_and_is_encrypted_at_rest():
    url = "ntfy://ntfy.sh/topic-secret-123"
    token = encrypt_url(url)

    assert "topic-secret-123" not in token
    assert decrypt_url(token) == url


def test_url_hint_drops_credentials_and_path():
    assert url_hint("mailto://user:pw@gmail.com?to=a@b.c") == "mailto://gmail.com/..."
    assert url_hint("ntfy://ntfy.sh/topic-secret-123") == "ntfy://ntfy.sh/..."
    assert "secret" not in url_hint("https://hooks.example.test:8443/services/secret")
