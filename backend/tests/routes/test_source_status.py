from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from app.models.library import Library
from app.models.novel import Novel
from app.models.user import User
from app.services.source_status_service import summarize_site
from tests.auth_helpers import bearer_headers

NOW = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


def _user(db, name: str) -> User:
    user = User(username=name, password="hashed_password_here")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _novel(db, user: User, site: str, title: str) -> None:
    library = Library(name=f"{title} lib", user_id=user.id)
    db.add(library)
    db.commit()
    db.add(Novel(title=title, url=f"https://example.test/{title}", library_id=library.id, novel_site=site))
    db.commit()


def test_summarize_maps_rate_limit_with_until():
    until = NOW + timedelta(minutes=40)
    row = summarize_site("fanfiction", {"status": "rate_limited", "rate_limit_until": until.isoformat()}, NOW)
    assert row == {
        "site": "fanfiction",
        "label": "FanFiction.net",
        "state": "rate_limited",
        "until": until.isoformat(),
        "message": "FanFiction.net is rate-limiting us.",
    }


def test_summarize_drops_expired_cooldown_and_maps_states():
    expired = (NOW - timedelta(minutes=1)).isoformat()
    assert summarize_site("ao3", {"status": "operational", "rate_limit_until": expired}, NOW)["state"] == "ok"
    assert summarize_site("ao3", {"status": "offline", "circuit_state": "open"}, NOW)["state"] == "down"
    assert summarize_site("ao3", {"status": "degraded", "circuit_state": "half-open"}, NOW)["state"] == "degraded"


def test_summarize_hides_internal_fields():
    row = summarize_site("royalroad", {"status": "offline", "last_error": "db password x", "failure_count": 9}, NOW)
    assert set(row) == {"site", "label", "state", "until", "message"}
    assert "db password" not in row["message"]


def test_status_lists_only_sites_the_user_reads(client, db):
    me = _user(db, "reader_one")
    other = _user(db, "reader_two")
    _novel(db, me, "fanfiction", "mine-ffn")
    _novel(db, other, "ao3", "theirs-ao3")
    health = [
        {"site": "fanfiction", "status": "rate_limited", "circuit_state": "closed", "rate_limit_until": (NOW + timedelta(hours=1)).isoformat()},
        {"site": "ao3", "status": "offline", "circuit_state": "open"},
    ]
    with patch("app.services.source_status_service.metadata_client.source_health", new=AsyncMock(return_value=health)):
        response = client.get("/sources/status", headers=bearer_headers(me.id))
    assert response.status_code == 200
    sites = response.json()["sites"]
    assert [item["site"] for item in sites] == ["fanfiction"]
    assert sites[0]["state"] == "rate_limited"


def test_status_empty_when_metadata_unreachable(client, db):
    me = _user(db, "reader_three")
    _novel(db, me, "royalroad", "some-rr")
    with patch("app.services.source_status_service.metadata_client.source_health", new=AsyncMock(side_effect=RuntimeError("down"))):
        response = client.get("/sources/status", headers=bearer_headers(me.id))
    assert response.status_code == 200
    assert response.json() == {"sites": []}


def test_status_requires_sign_in(client):
    assert client.get("/sources/status").status_code == 401
