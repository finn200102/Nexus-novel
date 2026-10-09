"""Single sign-on against a mocked OpenID Connect provider.

The provider runs in-process behind an httpx mock transport: a discovery
document, a JWKS with a local RSA key, a token endpoint that checks the PKCE
verifier and returns an ID token signed with that key, and userinfo.
"""

import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from fastapi import status
from joserfc import jwt
from joserfc.jwk import RSAKey

from app.auth import oidc
from app.auth.sessions import REFRESH_COOKIE
from app.models.account import UserSession
from app.models.user import User
from app.services import account_service
from config.settings import settings
from tests.auth_helpers import bearer_headers

ISSUER = "https://idp.example.test"
CLIENT_ID = "nexus"


class Provider:
    def __init__(self):
        self.key = RSAKey.generate_key(2048, parameters={"kid": "k1", "use": "sig", "alg": "RS256"})
        self.claims: dict = {}
        self.overrides: dict = {}
        self.userinfo: dict = {}
        self.challenge = None
        self.nonce = None

    def id_token(self) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "subject-1",
            "iat": now,
            "exp": now + 300,
            "nonce": self.nonce,
            "preferred_username": "alice",
            "email": "alice@example.test",
            **self.claims,
            **self.overrides,
        }
        return jwt.encode({"alg": "RS256", "kid": "k1"}, claims, self.key)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/.well-known/openid-configuration":
            return httpx.Response(200, json={
                "issuer": ISSUER,
                "authorization_endpoint": f"{ISSUER}/authorize",
                "token_endpoint": f"{ISSUER}/token",
                "jwks_uri": f"{ISSUER}/jwks",
                "userinfo_endpoint": f"{ISSUER}/userinfo",
                "id_token_signing_alg_values_supported": ["RS256"],
            })
        if path == "/jwks":
            return httpx.Response(200, json={"keys": [self.key.as_dict(private=False)]})
        if path == "/token":
            form = parse_qs(request.content.decode())
            verifier = form.get("code_verifier", [""])[0]
            if form.get("code") != ["good-code"] or create_s256_code_challenge(verifier) != self.challenge:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={
                "access_token": "at", "token_type": "Bearer", "expires_in": 300, "id_token": self.id_token(),
            })
        if path == "/userinfo":
            return httpx.Response(200, json={"sub": self.claims.get("sub", "subject-1"), **self.userinfo})
        return httpx.Response(404)


@pytest.fixture
def provider(monkeypatch):
    idp = Provider()
    monkeypatch.setattr(settings, "NEXUS_OIDC_ISSUER", ISSUER)
    monkeypatch.setattr(settings, "NEXUS_OIDC_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(settings, "NEXUS_OIDC_CLIENT_SECRET", "secret")
    monkeypatch.setattr(settings, "NEXUS_OIDC_DISPLAY_NAME", "Authelia")
    monkeypatch.setattr(settings, "NEXUS_OIDC_ADMIN_GROUP", "")
    monkeypatch.setattr(settings, "NEXUS_OIDC_AUTO_CREATE", "")
    monkeypatch.setattr(settings, "NEXUS_OIDC_REDIRECT_URI", "")
    monkeypatch.setattr(settings, "NEXUS_PASSWORD_LOGIN", "enabled")
    monkeypatch.setattr(oidc, "transport", httpx.MockTransport(idp.handle))
    oidc.reset_cache()
    yield idp
    oidc.reset_cache()


def start(client, provider, path="/auth/oidc/login", **kwargs):
    if path.endswith("/link"):
        response = client.post(path, **kwargs)
        location = response.json()["authorization_url"]
    else:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == status.HTTP_302_FOUND
        location = response.headers["location"]
    params = {k: v[0] for k, v in parse_qs(urlparse(location).query).items()}
    assert params["code_challenge_method"] == "S256"
    assert params["redirect_uri"] == "http://testserver/auth/oidc/callback"
    provider.challenge = params["code_challenge"]
    provider.nonce = params["nonce"]
    return params["state"]


def sign_in(client, provider, state=None, code="good-code"):
    real_state = start(client, provider)
    return client.get(
        "/auth/oidc/callback",
        params={"state": state or real_state, "code": code},
        follow_redirects=False,
    )


def sso_error(response) -> str | None:
    return parse_qs(urlparse(response.headers["location"]).query).get("sso_error", [None])[0]


def make_user(db, username, *, admin=False, password="", **extra):
    user = User(username=username, password=password, is_admin=admin, **extra)
    db.add(user)
    db.commit()
    return user


def test_config_reports_single_sign_on(client, provider):
    body = client.get("/auth/config").json()
    assert body["oidc"] == {"display_name": "Authelia"}
    assert body["password_login"] is True


def test_happy_path_creates_the_first_user_and_a_session(client, db, provider):
    response = sign_in(client, provider)

    assert response.status_code == status.HTTP_303_SEE_OTHER
    assert response.headers["location"] == "/"
    user = db.query(User).one()
    assert (user.username, user.oidc_issuer, user.oidc_subject) == ("alice", ISSUER, "subject-1")
    assert user.is_admin and user.password == ""
    # The app takes over with the usual refresh-cookie flow.
    refreshed = client.post("/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["username"] == "alice"

    # A second sign-in reuses the same account.
    client.cookies.clear()
    assert sign_in(client, provider).headers["location"] == "/"
    assert db.query(User).count() == 1
    assert db.query(UserSession).count() == 2


def test_bad_state_is_rejected(client, db, provider):
    response = sign_in(client, provider, state="forged")
    assert sso_error(response) == "state"
    assert REFRESH_COOKIE not in response.cookies
    assert db.query(User).count() == 0


def test_callback_without_flow_cookie_is_rejected(client, db, provider):
    start(client, provider)
    client.cookies.clear()
    response = client.get("/auth/oidc/callback", params={"state": "x", "code": "good-code"}, follow_redirects=False)
    assert sso_error(response) == "state"


def test_wrong_pkce_verifier_or_code_fails(client, db, provider):
    assert sso_error(sign_in(client, provider, code="other")) == "exchange_failed"
    assert db.query(User).count() == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"nonce": "replayed"},
        {"aud": "another-client"},
        {"iss": "https://evil.example.test"},
        {"exp": int(time.time()) - 600},
    ],
    ids=["bad-nonce", "wrong-audience", "wrong-issuer", "expired"],
)
def test_invalid_id_tokens_are_rejected(client, db, provider, overrides):
    provider.overrides = overrides
    response = sign_in(client, provider)
    assert sso_error(response) == "invalid_token"
    assert REFRESH_COOKIE not in response.cookies
    assert db.query(User).count() == 0


def test_token_signed_by_another_key_is_rejected(client, db, provider):
    real_key = provider.key
    provider.key = RSAKey.generate_key(2048, parameters={"kid": "k1"})
    original = provider.handle

    def handle(request):
        if request.url.path == "/jwks":
            return httpx.Response(200, json={"keys": [real_key.as_dict(private=False)]})
        return original(request)

    oidc.transport = httpx.MockTransport(handle)
    assert sso_error(sign_in(client, provider)) == "invalid_token"


def test_admin_group_maps_to_admin_on_each_login(client, db, provider, monkeypatch):
    monkeypatch.setattr(settings, "NEXUS_OIDC_ADMIN_GROUP", "nexus-admins")
    make_user(db, "owner", admin=True, password="x")
    account_service.set_signup_mode(db, "open")
    db.commit()

    provider.claims = {"groups": ["nexus-admins"]}
    sign_in(client, provider)
    user = db.query(User).filter(User.username == "alice").one()
    assert user.is_admin

    # Groups may come from userinfo instead of the ID token.
    provider.claims = {}
    provider.userinfo = {"groups": ["readers"]}
    client.cookies.clear()
    sign_in(client, provider)
    db.refresh(user)
    assert not user.is_admin


def test_last_admin_is_never_demoted(client, db, provider, monkeypatch):
    monkeypatch.setattr(settings, "NEXUS_OIDC_ADMIN_GROUP", "nexus-admins")
    sign_in(client, provider)  # first account: administrator
    user = db.query(User).one()
    assert user.is_admin

    client.cookies.clear()
    provider.claims = {"groups": ["readers"]}
    response = sign_in(client, provider)
    assert response.headers["location"] == "/"
    db.refresh(user)
    assert user.is_admin


def test_matching_username_or_email_never_takes_over_an_account(client, db, provider):
    victim = make_user(db, "alice", admin=True, password="hash")
    account_service.set_signup_mode(db, "open")
    db.commit()

    sign_in(client, provider)

    db.refresh(victim)
    assert victim.oidc_subject is None
    created = db.query(User).filter(User.oidc_subject == "subject-1").one()
    assert created.id != victim.id
    assert created.username == "alice-2"
    assert not created.is_admin


def test_closed_signup_refuses_unknown_identities_unless_auto_create_is_forced(client, db, provider, monkeypatch):
    make_user(db, "owner", admin=True, password="x")

    assert sso_error(sign_in(client, provider)) == "no_account"
    assert db.query(User).count() == 1

    monkeypatch.setattr(settings, "NEXUS_OIDC_AUTO_CREATE", "true")
    client.cookies.clear()
    assert sign_in(client, provider).headers["location"] == "/"
    assert db.query(User).count() == 2


def test_auto_create_false_never_creates(client, db, provider, monkeypatch):
    make_user(db, "owner", admin=True, password="x")
    account_service.set_signup_mode(db, "open")
    db.commit()
    monkeypatch.setattr(settings, "NEXUS_OIDC_AUTO_CREATE", "false")
    assert sso_error(sign_in(client, provider)) == "no_account"


def test_disabled_account_cannot_sign_in(client, db, provider):
    make_user(db, "bob", password="x", is_disabled=True, oidc_issuer=ISSUER, oidc_subject="subject-1")
    response = sign_in(client, provider)
    assert sso_error(response) == "disabled"
    assert REFRESH_COOKIE not in response.cookies


def test_signed_in_user_links_and_unlinks(client, db, provider):
    user = make_user(db, "carol", password="x")
    headers = bearer_headers(user.id)

    state = start(client, provider, "/auth/oidc/link", headers=headers)
    response = client.get("/auth/oidc/callback", params={"state": state, "code": "good-code"}, follow_redirects=False)

    assert response.headers["location"] == "/settings/account?sso=linked"
    assert REFRESH_COOKIE not in response.cookies
    db.refresh(user)
    assert (user.oidc_issuer, user.oidc_subject) == (ISSUER, "subject-1")
    assert client.get("/auth/oidc/status", headers=headers).json()["linked"] is True

    # Signing in through the provider now reaches the linked account.
    client.cookies.clear()
    sign_in(client, provider)
    assert db.query(User).count() == 1

    assert client.delete("/auth/oidc/link", headers=headers).status_code == 200
    db.refresh(user)
    assert user.oidc_subject is None


def test_identity_linked_elsewhere_cannot_be_linked_again(client, db, provider):
    make_user(db, "first", password="x", oidc_issuer=ISSUER, oidc_subject="subject-1")
    other = make_user(db, "second", password="x")
    state = start(client, provider, "/auth/oidc/link", headers=bearer_headers(other.id))
    response = client.get("/auth/oidc/callback", params={"state": state, "code": "good-code"}, follow_redirects=False)
    assert sso_error(response) == "already_linked"
    db.refresh(other)
    assert other.oidc_subject is None


def test_only_sign_in_method_cannot_be_unlinked(client, db, provider):
    user = make_user(db, "dave", oidc_issuer=ISSUER, oidc_subject="subject-1")
    response = client.delete("/auth/oidc/link", headers=bearer_headers(user.id))
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    db.refresh(user)
    assert user.oidc_subject == "subject-1"


def test_sso_user_can_set_a_first_password(client, db, provider):
    user = make_user(db, "erin", oidc_issuer=ISSUER, oidc_subject="subject-1")
    response = client.post(
        "/auth/password",
        json={"current_password": "", "new_password": "a-new-password"},
        headers=bearer_headers(user.id),
    )
    assert response.status_code == 200
    db.refresh(user)
    assert user.password


def test_password_login_can_be_disabled(client, db, provider, monkeypatch):
    make_user(db, "owner", admin=True, password="x")
    monkeypatch.setattr(settings, "NEXUS_PASSWORD_LOGIN", "disabled")

    assert client.get("/auth/config").json()["password_login"] is False
    login = client.post("/auth/login", json={"username": "owner", "password": "whatever"})
    assert login.status_code == status.HTTP_403_FORBIDDEN
    signup = client.post("/auth/signup", json={"username": "new", "password": "password123"})
    assert signup.status_code == status.HTTP_403_FORBIDDEN


def test_password_login_stays_on_without_single_sign_on(client, monkeypatch):
    monkeypatch.setattr(settings, "NEXUS_OIDC_ISSUER", "")
    monkeypatch.setattr(settings, "NEXUS_PASSWORD_LOGIN", "disabled")
    assert client.get("/auth/config").json()["password_login"] is True
    assert client.get("/auth/oidc/login", follow_redirects=False).status_code == status.HTTP_404_NOT_FOUND
