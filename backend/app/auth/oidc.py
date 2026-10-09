"""Single sign-on through an OpenID Connect provider.

Authorization code flow with PKCE, state and nonce. The provider's discovery
document and signing keys are fetched and cached; the ID token's signature,
issuer, audience, expiry and nonce are checked before Nexus trusts any claim.

The values a callback needs (state, nonce, PKCE verifier, and the user who is
linking, if any) travel in a short-lived signed cookie. It is SameSite=Lax
because the provider sends the browser back with a cross-site navigation.
"""

import hmac
import time
from dataclasses import dataclass
from urllib.parse import quote, urlencode

import httpx
from authlib.common.security import generate_token
from authlib.oauth2.rfc7636 import create_s256_code_challenge
from fastapi import Request, Response
from jose import JWTError, jwt as jose_jwt
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import JWTClaimsRegistry

from app.auth.sessions import _cookie_secure
from app.logging_config import get_logger
from config.settings import settings

logger = get_logger(__name__)

FLOW_COOKIE = "nexus_oidc_flow"
FLOW_LIFETIME_SECONDS = 600
METADATA_TTL_SECONDS = 3600
CLOCK_SKEW_SECONDS = 60
# Symmetric algorithms would let anyone holding the client secret mint tokens;
# "none" is never acceptable.
ALLOWED_ALGORITHMS = ["RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"]


class OIDCError(Exception):
    """A failed sign-in; ``code`` is shown to the login page."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


@dataclass
class Flow:
    state: str
    nonce: str
    verifier: str
    link_user_id: int | None = None


@dataclass
class Identity:
    issuer: str
    subject: str
    claims: dict


# Cached provider metadata and keys: {"discovery": (fetched_at, doc), "jwks": ...}
_cache: dict[str, tuple[float, dict]] = {}


# Tests route provider requests to a mock through this transport.
transport: httpx.BaseTransport | None = None


def http_client() -> httpx.Client:
    return httpx.Client(timeout=10, transport=transport)


def reset_cache() -> None:
    _cache.clear()


def _get_json(url: str) -> dict:
    try:
        with http_client() as client:
            response = client.get(url)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("oidc_provider_unreachable", url=url, error=str(exc))
        raise OIDCError("provider_unavailable") from exc


def discovery() -> dict:
    cached = _cache.get("discovery")
    if cached and time.time() - cached[0] < METADATA_TTL_SECONDS:
        return cached[1]
    issuer = settings.NEXUS_OIDC_ISSUER.strip()
    doc = _get_json(issuer.rstrip("/") + "/.well-known/openid-configuration")
    # The issuer in the document must be the one configured, byte for byte
    # apart from a trailing slash; ID tokens are then checked against it.
    if str(doc.get("issuer", "")).rstrip("/") != issuer.rstrip("/"):
        logger.warning("oidc_issuer_mismatch", configured=issuer, discovered=doc.get("issuer"))
        raise OIDCError("provider_misconfigured")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not doc.get(key):
            raise OIDCError("provider_misconfigured")
    _cache["discovery"] = (time.time(), doc)
    return doc


def _keys(refresh: bool = False) -> KeySet:
    cached = _cache.get("jwks")
    if refresh or not cached or time.time() - cached[0] >= METADATA_TTL_SECONDS:
        cached = (time.time(), _get_json(discovery()["jwks_uri"]))
        _cache["jwks"] = cached
    try:
        return KeySet.import_key_set(cached[1])
    except (JoseError, ValueError, TypeError) as exc:
        raise OIDCError("provider_misconfigured") from exc


def redirect_uri(request: Request) -> str:
    configured = settings.NEXUS_OIDC_REDIRECT_URI.strip()
    if configured:
        return configured
    # Behind the bundled nginx the API lives under /api.
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme).split(",")[0].strip()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).split(",")[0].strip()
    prefix = "/api" if request.headers.get("x-real-ip") else ""
    return f"{proto}://{host}{prefix}/auth/oidc/callback"


# The flow cookie


def new_flow(link_user_id: int | None = None) -> Flow:
    return Flow(state=generate_token(32), nonce=generate_token(32), verifier=generate_token(64), link_user_id=link_user_id)


def authorization_url(flow: Flow, request: Request) -> str:
    params = {
        "response_type": "code",
        "client_id": settings.NEXUS_OIDC_CLIENT_ID,
        "redirect_uri": redirect_uri(request),
        "scope": settings.NEXUS_OIDC_SCOPES.strip() or "openid",
        "state": flow.state,
        "nonce": flow.nonce,
        "code_challenge": create_s256_code_challenge(flow.verifier),
        "code_challenge_method": "S256",
    }
    endpoint = discovery()["authorization_endpoint"]
    return endpoint + ("&" if "?" in endpoint else "?") + urlencode(params)


def set_flow_cookie(response: Response, request: Request, flow: Flow) -> None:
    payload = {
        "purpose": "oidc_flow",
        "state": flow.state,
        "nonce": flow.nonce,
        "verifier": flow.verifier,
        "link": flow.link_user_id,
        "exp": int(time.time()) + FLOW_LIFETIME_SECONDS,
    }
    response.set_cookie(
        FLOW_COOKIE,
        jose_jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM),
        max_age=FLOW_LIFETIME_SECONDS,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(request),
        path="/",
    )


def clear_flow_cookie(response: Response, request: Request) -> None:
    response.delete_cookie(FLOW_COOKIE, path="/", httponly=True, samesite="lax", secure=_cookie_secure(request))


def read_flow(request: Request, returned_state: str | None) -> Flow:
    raw = request.cookies.get(FLOW_COOKIE)
    if not raw or not returned_state:
        raise OIDCError("state")
    try:
        payload = jose_jwt.decode(raw, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise OIDCError("state") from exc
    if payload.get("purpose") != "oidc_flow" or not hmac.compare_digest(
        str(payload.get("state", "")), returned_state
    ):
        raise OIDCError("state")
    return Flow(
        state=payload["state"],
        nonce=payload["nonce"],
        verifier=payload["verifier"],
        link_user_id=payload.get("link"),
    )


# The callback


def _validate_id_token(id_token: str, nonce: str) -> dict:
    doc = discovery()
    supported = doc.get("id_token_signing_alg_values_supported") or ["RS256"]
    algorithms = [alg for alg in supported if alg in ALLOWED_ALGORITHMS] or ["RS256"]
    try:
        try:
            token = jwt.decode(id_token, _keys(), algorithms=algorithms)
        except (JoseError, ValueError):
            # The provider may have rotated its keys since they were cached.
            token = jwt.decode(id_token, _keys(refresh=True), algorithms=algorithms)
    except (JoseError, ValueError) as exc:
        raise OIDCError("invalid_token", f"signature: {exc}") from exc

    claims = dict(token.claims)
    registry = JWTClaimsRegistry(
        now=lambda: int(time.time()),
        leeway=CLOCK_SKEW_SECONDS,
        iss={"essential": True, "value": doc["issuer"]},
        aud={"essential": True, "value": settings.NEXUS_OIDC_CLIENT_ID},
        sub={"essential": True},
        exp={"essential": True},
        nonce={"essential": True, "value": nonce},
    )
    try:
        registry.validate(claims)
    except JoseError as exc:
        raise OIDCError("invalid_token", str(exc)) from exc
    audience = claims.get("aud")
    if isinstance(audience, list) and len(audience) > 1 and claims.get("azp") != settings.NEXUS_OIDC_CLIENT_ID:
        raise OIDCError("invalid_token", "azp")
    return claims


def _userinfo(access_token: str | None, subject: str) -> dict:
    """Extra claims (groups, username) some providers only put in userinfo."""
    endpoint = discovery().get("userinfo_endpoint")
    if not endpoint or not access_token:
        return {}
    try:
        with http_client() as client:
            response = client.get(endpoint, headers={"Authorization": f"Bearer {access_token}"})
            response.raise_for_status()
            info = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("oidc_userinfo_failed", error=str(exc))
        return {}
    # Userinfo for a different subject is ignored (OIDC Core 5.3.2).
    return info if isinstance(info, dict) and info.get("sub") == subject else {}


def complete(request: Request, flow: Flow, code: str | None) -> Identity:
    """Exchange the code and return the verified identity."""
    if not code:
        raise OIDCError("state")
    doc = discovery()
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(request),
        "code_verifier": flow.verifier,
        "client_id": settings.NEXUS_OIDC_CLIENT_ID,
    }
    auth = None
    if settings.NEXUS_OIDC_CLIENT_SECRET:
        # client_secret_basic; RFC 6749 2.3.1 form-encodes both parts.
        auth = (quote(settings.NEXUS_OIDC_CLIENT_ID, safe=""), quote(settings.NEXUS_OIDC_CLIENT_SECRET, safe=""))
    try:
        with http_client() as client:
            response = client.post(doc["token_endpoint"], data=form, auth=auth, headers={"Accept": "application/json"})
            response.raise_for_status()
            token = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("oidc_code_exchange_failed", error=str(exc))
        raise OIDCError("exchange_failed") from exc
    if not isinstance(token, dict):
        raise OIDCError("exchange_failed")
    id_token = token.get("id_token")
    if not id_token:
        raise OIDCError("invalid_token", "no id_token")
    claims = _validate_id_token(id_token, flow.nonce)
    # Some providers put groups or the username only in userinfo; the
    # signed ID token wins where both carry a claim.
    merged = {**_userinfo(token.get("access_token"), claims["sub"]), **claims}
    return Identity(issuer=doc["issuer"], subject=str(claims["sub"]), claims=merged)


def groups(claims: dict) -> list[str]:
    value = claims.get(settings.NEXUS_OIDC_GROUPS_CLAIM)
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []
