# routers/oidc.py
"""Single sign-on endpoints.

``/login`` starts a sign-in, ``/link`` (signed in) starts linking the current
account, and ``/callback`` finishes either. A provider identity is matched to
an account only by issuer and subject; an e-mail or username that happens to
match an existing account never signs anyone into it.
"""

import re
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit import AuditAction, audit
from app.auth import oidc
from app.auth.dependencies import get_current_user
from app.auth.oidc import Identity, OIDCError
from app.auth.sessions import set_refresh_cookie, start_session
from app.logging_config import get_logger
from app.models.user import User
from app.services import account_service
from config.database import get_db
from config.settings import settings

logger = get_logger(__name__)

# Mounted under the /auth router.
router = APIRouter(prefix="/oidc")

LOGIN_PAGE = "/login"
ACCOUNT_PAGE = "/settings/account"
APP_HOME = "/"


def _require_enabled() -> None:
    if not settings.oidc_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Single sign-on is not configured.")


def _redirect(path: str, request: Request, **params: str) -> RedirectResponse:
    url = path + ("?" + urlencode(params) if params else "")
    response = RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)
    oidc.clear_flow_cookie(response, request)
    return response


def has_password(user: User) -> bool:
    return bool(user.password) and not user.password.startswith("\\x")


def auto_create_allowed(db: Session) -> bool:
    if not account_service.has_users(db):
        # Like password sign-up, the first account is always allowed.
        return True
    choice = settings.NEXUS_OIDC_AUTO_CREATE.strip().lower()
    if choice in {"false", "0", "no"}:
        return False
    if choice in {"true", "1", "yes"}:
        return True
    # Default: follow the instance's sign-up mode. "invite" still allows it,
    # since the provider decides who can authenticate at all.
    return account_service.get_signup_mode(db) != "closed"


def _unique_username(db: Session, claims: dict) -> str:
    raw = claims.get(settings.NEXUS_OIDC_USERNAME_CLAIM) or claims.get("preferred_username") or ""
    if not raw and isinstance(claims.get("email"), str):
        raw = claims["email"].split("@", 1)[0]
    base = re.sub(r"\s+", "-", str(raw).strip())[:56] or "user"
    candidate, suffix = base, 1
    # A name that is already taken gets a suffix; it is never linked.
    while db.query(User.id).filter(func.lower(User.username) == candidate.lower()).first():
        suffix += 1
        candidate = f"{base}-{suffix}"
    return candidate


def _apply_admin_group(db: Session, user: User, claims: dict) -> None:
    group = settings.NEXUS_OIDC_ADMIN_GROUP.strip()
    if not group:
        return
    should_be_admin = group in oidc.groups(claims)
    if should_be_admin and not user.is_admin:
        user.is_admin = True
        audit.log(AuditAction.USER_UPDATED, user_id=user.id, details={"is_admin": True, "source": "oidc"})
    elif not should_be_admin and user.is_admin:
        try:
            account_service.ensure_admin_remains(db, user)
        except account_service.AccountError:
            logger.warning("oidc_kept_last_admin", user_id=user.id)
            return
        user.is_admin = False
        audit.log(AuditAction.USER_UPDATED, user_id=user.id, details={"is_admin": False, "source": "oidc"})


def _find_linked(db: Session, identity: Identity) -> User | None:
    return (
        db.query(User)
        .filter(User.oidc_issuer == identity.issuer, User.oidc_subject == identity.subject)
        .first()
    )


@router.get("/login")
def oidc_login(request: Request):
    """Send the browser to the provider."""
    _require_enabled()
    flow = oidc.new_flow()
    try:
        url = oidc.authorization_url(flow, request)
    except OIDCError as exc:
        return _redirect(LOGIN_PAGE, request, sso_error=exc.code)
    response = RedirectResponse(url, status_code=status.HTTP_302_FOUND)
    oidc.set_flow_cookie(response, request, flow)
    return response


@router.get("/status")
def oidc_status(current_user: User = Depends(get_current_user)):
    """Linked sign-in state for Settings."""
    return {
        "enabled": settings.oidc_enabled,
        "display_name": settings.NEXUS_OIDC_DISPLAY_NAME,
        "linked": bool(current_user.oidc_subject),
        "has_password": has_password(current_user),
        "password_login": settings.password_login_enabled,
    }


@router.post("/link")
def oidc_link(request: Request, current_user: User = Depends(get_current_user)):
    """Start linking the signed-in account; the browser then visits the URL."""
    _require_enabled()
    flow = oidc.new_flow(link_user_id=current_user.id)
    try:
        url = oidc.authorization_url(flow, request)
    except OIDCError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="The sign-in provider is unavailable.") from exc
    response = JSONResponse({"authorization_url": url})
    oidc.set_flow_cookie(response, request, flow)
    return response


@router.delete("/link")
def oidc_unlink(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not current_user.oidc_subject:
        return {"message": "No sign-in is linked."}
    if not has_password(current_user) or not settings.password_login_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This is your only way to sign in. Set a password first.",
        )
    current_user.oidc_issuer = None
    current_user.oidc_subject = None
    db.commit()
    audit.log(AuditAction.SSO_UNLINKED, user_id=current_user.id)
    return {"message": "Sign-in unlinked."}


@router.get("/callback")
def oidc_callback(
    request: Request,
    state: str | None = None,
    code: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
):
    _require_enabled()
    try:
        flow = oidc.read_flow(request, state)
    except OIDCError as exc:
        return _redirect(LOGIN_PAGE, request, sso_error=exc.code)
    back = ACCOUNT_PAGE if flow.link_user_id else LOGIN_PAGE
    if error:
        return _redirect(back, request, sso_error="denied")
    try:
        identity = oidc.complete(request, flow, code)
    except OIDCError as exc:
        logger.warning("oidc_sign_in_failed", reason=str(exc))
        return _redirect(back, request, sso_error=exc.code)

    linked = _find_linked(db, identity)

    if flow.link_user_id:
        user = db.get(User, flow.link_user_id)
        if user is None or user.is_disabled:
            return _redirect(LOGIN_PAGE, request, sso_error="state")
        if linked is not None and linked.id != user.id:
            return _redirect(ACCOUNT_PAGE, request, sso_error="already_linked")
        user.oidc_issuer = identity.issuer
        user.oidc_subject = identity.subject
        db.commit()
        audit.log(AuditAction.SSO_LINKED, user_id=user.id)
        return _redirect(ACCOUNT_PAGE, request, sso="linked")

    user = linked
    if user is None:
        if not auto_create_allowed(db):
            return _redirect(LOGIN_PAGE, request, sso_error="no_account")
        first_user = not account_service.has_users(db)
        user = User(
            username=_unique_username(db, identity.claims),
            password="",
            is_admin=first_user,
            oidc_issuer=identity.issuer,
            oidc_subject=identity.subject,
        )
        db.add(user)
        db.flush()
        audit.log(AuditAction.USER_SIGNUP, user_id=user.id, details={"admin": first_user, "source": "oidc"})
    elif user.is_disabled:
        audit.log(AuditAction.USER_LOGIN, user_id=user.id, success=False)
        return _redirect(LOGIN_PAGE, request, sso_error="disabled")

    _apply_admin_group(db, user, identity.claims)
    session, refresh_token = start_session(db, user, request)
    db.commit()
    audit.log(AuditAction.USER_LOGIN, user_id=user.id, details={"source": "oidc"})
    # The app picks the session up through the refresh cookie on load.
    response = _redirect(APP_HOME, request)
    set_refresh_cookie(response, request, refresh_token)
    return response
