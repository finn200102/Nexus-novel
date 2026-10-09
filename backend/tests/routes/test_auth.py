from datetime import timedelta
from pathlib import Path

import pytest
from fastapi import status

from app.auth import rate_limit
from app.auth.jwt import verify_token
from app.auth.sessions import REFRESH_COOKIE, utcnow
from app.models.account import AuthAttempt, RefreshToken, UserSession
from app.models.audio_job import ChapterAudioJob
from app.models.chapter import Chapter
from app.models.ereader import EpubBuild
from app.models.library import Library
from app.models.novel import Novel
from app.models.user import User
from app.services import account_service
from app.services.epub_service import epub_dir
from app.services.user_services import get_user_by_username
from config.settings import settings
from tests.auth_helpers import bearer_headers

PASSWORD = "password123"


def signup(client, username, password=PASSWORD, **extra):
    return client.post("/auth/signup", json={"username": username, "password": password, **extra})


def login(client, username, password=PASSWORD):
    return client.post("/auth/login", json={"username": username, "password": password})


def bearer(response) -> dict[str, str]:
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def refresh_with(client, cookie):
    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE, cookie)
    return client.post("/auth/refresh")


def admin_client(client):
    """Sign up the first account, which becomes the administrator."""
    response = signup(client, "admin")
    assert response.status_code == status.HTTP_201_CREATED
    return bearer(response)


def set_signup_mode(client, headers, mode):
    response = client.put("/admin/settings", json={"signup_mode": mode}, headers=headers)
    assert response.status_code == status.HTTP_200_OK, response.text


# Sign-up policy

def test_first_signup_becomes_admin_and_gets_a_session(client, db):
    response = signup(client, "testuser")

    assert response.status_code == status.HTTP_201_CREATED
    body = response.json()
    assert body["username"] == "testuser"
    assert body["is_admin"] is True
    assert body["expires_in"] == 15 * 60
    assert verify_token(body["access_token"])["user_id"] == body["id"]
    assert client.cookies.get(REFRESH_COOKIE)
    cookie_header = response.headers["set-cookie"].lower()
    assert "httponly" in cookie_header and "samesite=strict" in cookie_header
    assert get_user_by_username(db, "testuser").first().is_admin is True


def test_signup_is_closed_once_an_admin_exists(client):
    admin_client(client)

    assert client.get("/auth/config").json() == {
        "signup_mode": "closed",
        "first_user": False,
        "password_login": True,
        "oidc": None,
    }
    response = signup(client, "second")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_open_signup_creates_regular_users_and_rejects_duplicates(client):
    headers = admin_client(client)
    set_signup_mode(client, headers, "open")

    first = signup(client, "reader")
    assert first.status_code == status.HTTP_201_CREATED
    assert first.json()["is_admin"] is False
    duplicate = signup(client, "reader")
    assert duplicate.status_code == status.HTTP_400_BAD_REQUEST
    assert "Username already registered" in duplicate.json()["detail"]


def test_usernames_are_unique_regardless_of_case(client, db):
    headers = admin_client(client)
    set_signup_mode(client, headers, "open")
    assert signup(client, "Reader").status_code == status.HTTP_201_CREATED

    duplicate = signup(client, "READER")
    assert duplicate.status_code == status.HTTP_400_BAD_REQUEST
    assert "Username already registered" in duplicate.json()["detail"]
    assert db.query(User).filter(User.username.ilike("reader")).count() == 1


def test_login_ignores_username_case(client, db):
    created = signup(client, "MixedCase").json()
    client.cookies.clear()

    response = login(client, "mixedcase")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == created["id"]
    assert get_user_by_username(db, "MIXEDCASE").first().id == created["id"]


def test_invite_mode_requires_a_valid_unused_invite(client):
    headers = admin_client(client)
    set_signup_mode(client, headers, "invite")
    invite = client.post("/admin/invites", json={"label": "Sam", "max_uses": 1}, headers=headers).json()
    assert invite["status"] == "active" and invite["code"]

    assert signup(client, "nocode").status_code == status.HTTP_403_FORBIDDEN
    assert signup(client, "badcode", invite_code="wrong").status_code == status.HTTP_403_FORBIDDEN
    assert signup(client, "sam", invite_code=invite["code"]).status_code == status.HTTP_201_CREATED
    assert signup(client, "again", invite_code=invite["code"]).status_code == status.HTTP_403_FORBIDDEN

    listed = client.get("/admin/invites", headers=headers).json()
    assert listed[0]["status"] == "used" and listed[0]["use_count"] == 1
    assert listed[0]["code"] is None


def test_revoked_and_expired_invites_are_rejected(client, db):
    headers = admin_client(client)
    set_signup_mode(client, headers, "invite")
    revoked = client.post("/admin/invites", json={"max_uses": None}, headers=headers).json()
    client.delete(f"/admin/invites/{revoked['id']}", headers=headers)
    expired = client.post("/admin/invites", json={}, headers=headers).json()
    from app.models.account import InviteCode

    db.get(InviteCode, expired["id"]).expires_at = utcnow() - timedelta(minutes=1)
    db.commit()

    assert signup(client, "one", invite_code=revoked["code"]).status_code == status.HTTP_403_FORBIDDEN
    assert signup(client, "two", invite_code=expired["code"]).status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.parametrize(
    "payload",
    [
        {"username": "shortpass", "password": "1234567"},
        {"username": "longpass", "password": "x" * 73},
        {"username": "   ", "password": "password123"},
    ],
)
def test_signup_rejects_invalid_credentials(client, db, payload):
    response = client.post("/auth/signup", json=payload)

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# Sign-in, refresh and sign-out

def test_login_success(client, db):
    created = signup(client, "testuser").json()
    client.cookies.clear()

    response = login(client, "testuser")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == created["id"]
    assert response.json()["message"] == "Login successful"
    assert client.get("/auth/me", headers=bearer(response)).json()["username"] == "testuser"


def test_login_rejects_wrong_password_and_disabled_users(client, db):
    signup(client, "testuser")
    assert login(client, "testuser", "wrong-password").status_code == status.HTTP_401_UNAUTHORIZED

    user = get_user_by_username(db, "testuser").first()
    user.is_disabled = True
    db.commit()
    assert login(client, "testuser").status_code == status.HTTP_401_UNAUTHORIZED


def test_access_token_without_a_session_is_rejected(client, db, test_user):
    from app.auth.jwt import create_access_token

    token = create_access_token({"sub": str(test_user.id)})
    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_refresh_rotates_the_cookie(client, db):
    signup(client, "testuser")
    first_cookie = client.cookies.get(REFRESH_COOKIE)

    response = client.post("/auth/refresh")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["username"] == "testuser"
    second_cookie = client.cookies.get(REFRESH_COOKIE)
    assert second_cookie and second_cookie != first_cookie
    assert client.get("/auth/me", headers=bearer(response)).status_code == status.HTTP_200_OK
    # Only hashes are stored.
    assert db.query(RefreshToken).filter(RefreshToken.token_hash == second_cookie).first() is None


def test_reused_refresh_token_revokes_the_session(client, db):
    session_response = signup(client, "testuser")
    stolen = client.cookies.get(REFRESH_COOKIE)
    assert client.post("/auth/refresh").status_code == status.HTTP_200_OK
    # Move the rotation outside the grace period for concurrent tabs.
    for token in db.query(RefreshToken).filter(RefreshToken.rotated_at.isnot(None)):
        token.rotated_at = utcnow() - timedelta(minutes=5)
    db.commit()

    client.cookies.clear()
    replay = refresh_with(client, stolen)

    assert replay.status_code == status.HTTP_401_UNAUTHORIZED
    # The whole session ends: the legitimate access token stops working too.
    assert client.get("/auth/me", headers=bearer(session_response)).status_code == status.HTTP_401_UNAUTHORIZED


def test_rotated_token_is_accepted_within_the_grace_period(client):
    signup(client, "testuser")
    cookie = client.cookies.get(REFRESH_COOKIE)
    assert client.post("/auth/refresh").status_code == status.HTTP_200_OK

    client.cookies.clear()
    assert refresh_with(client, cookie).status_code == status.HTTP_200_OK


def test_refresh_without_cookie_is_rejected(client):
    assert client.post("/auth/refresh").status_code == status.HTTP_401_UNAUTHORIZED


def test_logout_revokes_the_session(client):
    response = signup(client, "testuser")
    cookie = client.cookies.get(REFRESH_COOKIE)

    assert client.post("/auth/logout").status_code == status.HTTP_204_NO_CONTENT

    assert client.get("/auth/me", headers=bearer(response)).status_code == status.HTTP_401_UNAUTHORIZED
    assert refresh_with(client, cookie).status_code == status.HTTP_401_UNAUTHORIZED


def test_logout_other_devices_keeps_the_current_session(client):
    first = signup(client, "testuser")
    client.cookies.clear()
    second = login(client, "testuser")

    response = client.post("/auth/logout-others", headers=bearer(second))

    assert response.json() == {"revoked_sessions": 1}
    assert client.get("/auth/me", headers=bearer(first)).status_code == status.HTTP_401_UNAUTHORIZED
    assert client.get("/auth/me", headers=bearer(second)).status_code == status.HTTP_200_OK


# Passwords

def test_change_password_requires_current_password_and_signs_out_other_devices(client):
    other_device = signup(client, "testuser")
    client.cookies.clear()
    this_device = login(client, "testuser")

    wrong = client.post(
        "/auth/password",
        json={"current_password": "nope", "new_password": "new-password-1"},
        headers=bearer(this_device),
    )
    assert wrong.status_code == status.HTTP_400_BAD_REQUEST
    changed = client.post(
        "/auth/password",
        json={"current_password": PASSWORD, "new_password": "new-password-1"},
        headers=bearer(this_device),
    )
    assert changed.status_code == status.HTTP_200_OK

    assert client.get("/auth/me", headers=bearer(other_device)).status_code == status.HTTP_401_UNAUTHORIZED
    assert client.get("/auth/me", headers=bearer(this_device)).status_code == status.HTTP_200_OK
    assert login(client, "testuser").status_code == status.HTTP_401_UNAUTHORIZED
    assert login(client, "testuser", "new-password-1").status_code == status.HTTP_200_OK


def test_admin_reset_link_sets_a_new_password_once(client):
    headers = admin_client(client)
    set_signup_mode(client, headers, "open")
    user = signup(client, "forgetful")
    user_id = user.json()["id"]

    link = client.post(f"/admin/users/{user_id}/password-reset", json={}, headers=headers).json()
    assert link["path"] == f"/reset-password?token={link['token']}"

    reset = client.post("/auth/password-reset", json={"token": link["token"], "new_password": "brand-new-pass"})
    assert reset.status_code == status.HTTP_200_OK
    again = client.post("/auth/password-reset", json={"token": link["token"], "new_password": "another-pass"})
    assert again.status_code == status.HTTP_400_BAD_REQUEST

    # Existing sessions of that user ended.
    assert client.get("/auth/me", headers=bearer(user)).status_code == status.HTTP_401_UNAUTHORIZED
    assert login(client, "forgetful", "brand-new-pass").status_code == status.HTTP_200_OK


def test_new_reset_link_invalidates_the_previous_one(client):
    headers = admin_client(client)
    first = client.post("/admin/users/1/password-reset", json={}, headers=headers).json()
    client.post("/admin/users/1/password-reset", json={}, headers=headers)

    response = client.post("/auth/password-reset", json={"token": first["token"], "new_password": "brand-new-pass"})
    assert response.status_code == status.HTTP_400_BAD_REQUEST


# Rate limits

def test_login_is_rate_limited_per_username(client, db):
    signup(client, "target")
    for _ in range(rate_limit.LOGIN_FAILURES_PER_USER.max_attempts):
        assert login(client, "target", "wrong-password").status_code == status.HTTP_401_UNAUTHORIZED

    blocked = login(client, "target")
    assert blocked.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert int(blocked.headers["retry-after"]) > 0
    # The limit is stored, so it survives a restart of the API.
    assert db.query(AuthAttempt).filter(AuthAttempt.key == "login:user:target").count() == 10


def test_login_rate_limit_expires_after_the_window(client, db):
    signup(client, "target")
    for _ in range(rate_limit.LOGIN_FAILURES_PER_USER.max_attempts):
        login(client, "target", "wrong-password")
    for attempt in db.query(AuthAttempt):
        attempt.created_at = utcnow() - timedelta(minutes=16)
    db.commit()

    assert login(client, "target").status_code == status.HTTP_200_OK


def test_signup_is_rate_limited_per_address(client):
    headers = admin_client(client)
    set_signup_mode(client, headers, "open")
    for index in range(rate_limit.SIGNUPS_PER_IP.max_attempts - 1):
        signup(client, f"user{index}")

    assert signup(client, "one-too-many").status_code == status.HTTP_429_TOO_MANY_REQUESTS


# Administration

def test_admin_routes_require_an_administrator(client):
    admin_client(client)
    client.put("/admin/settings", json={"signup_mode": "open"}, headers=bearer(login(client, "admin")))
    reader = signup(client, "reader")

    assert client.get("/admin/users", headers=bearer(reader)).status_code == status.HTTP_403_FORBIDDEN
    assert client.post("/admin/invites", json={}, headers=bearer(reader)).status_code == status.HTTP_403_FORBIDDEN
    # Instance-wide metadata operations are administrator-only as well.
    assert client.get("/operations/schedules", headers=bearer(reader)).status_code == status.HTTP_403_FORBIDDEN
    assert client.post("/operations/metadata-jobs/x/retry", headers=bearer(reader)).status_code == status.HTTP_403_FORBIDDEN


def test_admin_lists_promotes_and_disables_users(client):
    headers = admin_client(client)
    set_signup_mode(client, headers, "open")
    reader = signup(client, "reader")
    reader_id = reader.json()["id"]

    users = client.get("/admin/users", headers=headers).json()
    assert [user["username"] for user in users] == ["admin", "reader"]
    assert users[1]["active_sessions"] == 1

    promoted = client.patch(f"/admin/users/{reader_id}", json={"is_admin": True}, headers=headers)
    assert promoted.json()["is_admin"] is True
    disabled = client.patch(f"/admin/users/{reader_id}", json={"is_disabled": True}, headers=headers)
    assert disabled.json()["is_disabled"] is True
    # Disabling ends the user's sessions immediately.
    assert client.get("/auth/me", headers=bearer(reader)).status_code == status.HTTP_401_UNAUTHORIZED
    assert login(client, "reader").status_code == status.HTTP_401_UNAUTHORIZED


def test_last_admin_cannot_be_demoted_disabled_or_deleted(client, db):
    headers = admin_client(client)
    admin_id = 1

    demote = client.patch(f"/admin/users/{admin_id}", json={"is_admin": False}, headers=headers)
    assert demote.status_code == status.HTTP_400_BAD_REQUEST
    assert client.patch(f"/admin/users/{admin_id}", json={"is_disabled": True}, headers=headers).status_code == 400
    assert client.delete(f"/admin/users/{admin_id}", headers=headers).status_code == 400

    # With a second administrator, demoting yourself is fine.
    db.add(User(username="other-admin", password="x", is_admin=True))
    db.commit()
    assert client.patch(f"/admin/users/{admin_id}", json={"is_admin": False}, headers=headers).status_code == 200


def test_admin_deletes_a_user_and_their_data(client, db):
    headers = admin_client(client)
    set_signup_mode(client, headers, "open")
    reader_id = signup(client, "reader").json()["id"]
    db.add(Library(name="Reader library", user_id=reader_id))
    db.commit()

    assert client.delete(f"/admin/users/{reader_id}", headers=headers).status_code == status.HTTP_204_NO_CONTENT

    assert db.get(User, reader_id) is None
    assert db.query(Library).filter(Library.user_id == reader_id).count() == 0
    assert db.query(UserSession).filter(UserSession.user_id == reader_id).count() == 0


def _write(path: Path, text: str = "data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_deleting_a_user_removes_their_files_after_the_commit(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DOWNLOAD_PATH", str(tmp_path / "downloads"))
    headers = admin_client(client)
    set_signup_mode(client, headers, "open")
    reader_id = signup(client, "reader").json()["id"]
    other_id = signup(client, "other").json()["id"]
    reader_library = Library(name="Reader library", user_id=reader_id)
    other_library = Library(name="Other library", user_id=other_id)
    db.add_all([reader_library, other_library])
    db.flush()
    novel = Novel(title="Kept", url="https://example.com/reader", library_id=reader_library.id, novel_site="royalroad")
    other_novel = Novel(title="Other", url="https://example.com/other", library_id=other_library.id, novel_site="royalroad")
    db.add_all([novel, other_novel])
    db.flush()
    chapter = Chapter(novel_id=novel.id, chapter_number=1, title="Chapter 1")
    db.add(chapter)
    db.flush()
    audio = _write(tmp_path / "audio" / "reader.wav")
    db.add(ChapterAudioJob(
        user_id=reader_id, library_id=reader_library.id, novel_id=novel.id, chapter_id=chapter.id,
        provider_id="local", provider_url="http://localhost", provider_model="m", provider_voice="v",
        audio_path=str(audio),
    ))
    reader_epub = _write(epub_dir() / f"{novel.id}-aaaa.epub")
    other_epub = _write(epub_dir() / f"{other_novel.id}-bbbb.epub")
    db.add_all([
        EpubBuild(novel_id=novel.id, fingerprint="a" * 64, partial_md5="a" * 32, size_bytes=4, file_name=reader_epub.name, spine=[]),
        EpubBuild(novel_id=other_novel.id, fingerprint="b" * 64, partial_md5="b" * 32, size_bytes=4, file_name=other_epub.name, spine=[]),
    ])
    reader_dir = _write(tmp_path / "downloads" / "reader" / str(reader_library.id) / "Kept" / "1.txt")
    other_dir = _write(tmp_path / "downloads" / "other" / str(other_library.id) / "Other" / "1.txt")
    db.commit()

    assert client.delete(f"/admin/users/{reader_id}", headers=headers).status_code == status.HTTP_204_NO_CONTENT

    assert not audio.exists()
    assert not reader_epub.exists()
    assert not reader_dir.parents[2].exists()
    assert other_epub.exists()
    assert other_dir.exists()


def test_user_files_are_kept_when_the_delete_does_not_commit(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DOWNLOAD_PATH", str(tmp_path / "downloads"))
    headers = admin_client(client)
    set_signup_mode(client, headers, "open")
    reader_id = signup(client, "reader").json()["id"]
    library = Library(name="Reader library", user_id=reader_id)
    db.add(library)
    db.commit()
    kept = _write(tmp_path / "downloads" / "reader" / str(library.id) / "Novel" / "1.txt")

    def failing_commit():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(db, "commit", failing_commit)
    with pytest.raises(RuntimeError):
        account_service.delete_user_account(db, db.get(User, reader_id))
    db.rollback()

    assert kept.exists()


def test_user_download_folders_outside_the_download_root_are_never_removed(db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DOWNLOAD_PATH", str(tmp_path / "downloads"))
    sibling = _write(tmp_path / "downloads-secret" / "1.txt")
    user = User(username="..", password="x")
    db.add(user)
    db.flush()
    db.add(Library(name="Escape", user_id=user.id))
    db.commit()

    account_service.delete_user_account(db, db.get(User, user.id))

    assert sibling.exists()


def test_signup_mode_rejects_unknown_values(client):
    headers = admin_client(client)
    response = client.put("/admin/settings", json={"signup_mode": "anyone"}, headers=headers)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_bearer_helper_matches_real_sessions(client, db, test_user):
    assert client.get("/auth/me", headers=bearer_headers(test_user.id, db)).status_code == status.HTTP_200_OK


def test_insecure_default_secret_is_replaced_by_persisted_key(tmp_path, monkeypatch):
    from config.settings import Settings

    monkeypatch.delenv("NEXUS_SECRET_KEY_FILE", raising=False)
    first = Settings(SECRET_KEY="nexus-local-development-secret-change-me", DOWNLOAD_PATH=str(tmp_path))
    second = Settings(SECRET_KEY="", DOWNLOAD_PATH=str(tmp_path))

    assert first.SECRET_KEY == second.SECRET_KEY
    assert len(first.SECRET_KEY) >= 32
    assert (tmp_path / ".nexus-secret-key").stat().st_mode & 0o777 == 0o600
    assert Settings(SECRET_KEY="operator-chosen", DOWNLOAD_PATH=str(tmp_path)).SECRET_KEY == "operator-chosen"
