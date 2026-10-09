# routers/auth.py
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.audit import AuditAction, audit
from app.auth import rate_limit
from app.auth.dependencies import Authenticated, get_current_auth, get_current_user
from app.auth.passwords import verify_password
from app.auth.sessions import (
    REFRESH_COOKIE,
    InvalidRefreshToken,
    clear_refresh_cookie,
    client_ip,
    revoke_session,
    revoke_user_sessions,
    rotate_refresh_token,
    session_for_refresh_token,
    set_refresh_cookie,
    start_session,
    token_response,
)
from app.models.user import User
from app.services import account_service
from app.services.account_service import AccountError
from app.services.user_services import get_user_by_username
from app.routers import oidc
from config.database import get_db
from config.settings import settings
from ..schemas.user import (
    LoginResponse,
    PasswordChange,
    PasswordReset,
    OIDCConfig,
    SignupConfig,
    User as UserSchema,
    UserCreate,
    UserLogin,
)

router = APIRouter(
    prefix="/auth",
    tags=["authentication"],
    responses={404: {"description": "Not found"}},
)


def _signed_in(db: Session, user: User, request: Request, response: Response, message: str) -> dict:
    session, refresh_token = start_session(db, user, request)
    db.commit()
    set_refresh_cookie(response, request, refresh_token)
    return token_response(user, session, message)


@router.get("/config", response_model=SignupConfig)
def signup_config(db: Session = Depends(get_db)):
    """What the sign-up page should offer; public."""
    return {
        "signup_mode": account_service.get_signup_mode(db),
        "first_user": not account_service.has_users(db),
        "password_login": settings.password_login_enabled,
        "oidc": OIDCConfig(display_name=settings.NEXUS_OIDC_DISPLAY_NAME) if settings.oidc_enabled else None,
    }


def _require_password_login() -> None:
    if not settings.password_login_enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password sign-in is disabled on this instance. Use single sign-on.",
        )


@router.post("/signup", response_model=LoginResponse, status_code=status.HTTP_201_CREATED)
def signup(user: UserCreate, request: Request, response: Response, db: Session = Depends(get_db)):
    _require_password_login()
    ip = client_ip(request)
    rate_limit.check(db, rate_limit.SIGNUPS_PER_IP, ip)
    rate_limit.record(db, rate_limit.SIGNUPS_PER_IP, ip)

    # The first account is always allowed and administers the instance.
    first_user = not account_service.has_users(db)
    if not first_user:
        mode = account_service.get_signup_mode(db)
        if mode == "closed":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sign-up is closed on this instance.")
        if mode == "invite":
            try:
                account_service.consume_invite(db, user.invite_code)
            except AccountError as exc:
                db.rollback()
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    if get_user_by_username(db, user.username).first():
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username already registered",
        )

    new_user = User(username=user.username, is_admin=first_user)
    account_service.set_password(db, new_user, user.password)
    db.add(new_user)
    db.flush()
    audit.log(AuditAction.USER_SIGNUP, user_id=new_user.id, details={"admin": first_user})
    return _signed_in(db, new_user, request, response, "Signup successful")


@router.post("/login", response_model=LoginResponse, status_code=status.HTTP_200_OK)
def login(user_data: UserLogin, request: Request, response: Response, db: Session = Depends(get_db)):
    _require_password_login()
    ip = client_ip(request)
    rate_limit.check(db, rate_limit.LOGIN_FAILURES_PER_IP, ip)
    rate_limit.check(db, rate_limit.LOGIN_FAILURES_PER_USER, user_data.username)

    user = get_user_by_username(db, user_data.username).first()
    if not user or not verify_password(user_data.password, user.password) or user.is_disabled:
        rate_limit.record(db, rate_limit.LOGIN_FAILURES_PER_IP, ip)
        rate_limit.record(db, rate_limit.LOGIN_FAILURES_PER_USER, user_data.username)
        audit.log(AuditAction.USER_LOGIN, user_id=user.id if user else None, success=False)
        # Same answer for a disabled account, so it does not reveal which
        # names exist or confirm a guessed password.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    rate_limit.clear(db, rate_limit.LOGIN_FAILURES_PER_USER, user_data.username)
    audit.log(AuditAction.USER_LOGIN, user_id=user.id)
    return _signed_in(db, user, request, response, "Login successful")


@router.post("/refresh", response_model=LoginResponse)
def refresh(request: Request, response: Response, db: Session = Depends(get_db)):
    """Exchange the refresh cookie for a new access token and a new cookie."""
    try:
        session, refresh_token = rotate_refresh_token(db, request.cookies.get(REFRESH_COOKIE), request)
    except InvalidRefreshToken:
        failed = JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Session ended. Please sign in again."},
        )
        clear_refresh_cookie(failed, request)
        return failed
    set_refresh_cookie(response, request, refresh_token)
    return token_response(db.get(User, session.user_id), session, "Session refreshed")


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, db: Session = Depends(get_db)):
    """End this device's session. Works without a valid access token so an
    expired tab can still sign out."""
    session = session_for_refresh_token(db, request.cookies.get(REFRESH_COOKIE))
    if session is not None:
        revoke_session(db, session)
        db.commit()
        audit.log(AuditAction.USER_LOGOUT, user_id=session.user_id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_refresh_cookie(response, request)
    return response


@router.post("/logout-others")
def logout_other_devices(auth: Authenticated = Depends(get_current_auth), db: Session = Depends(get_db)):
    revoked = revoke_user_sessions(db, auth.user.id, keep_session_id=auth.session.id)
    db.commit()
    return {"revoked_sessions": revoked}


@router.post("/password")
def change_password(
    payload: PasswordChange,
    auth: Authenticated = Depends(get_current_auth),
    db: Session = Depends(get_db),
):
    """Change your own password; other devices are signed out."""
    user = auth.user
    rate_limit.check(db, rate_limit.PASSWORD_FAILURES_PER_USER, str(user.id))
    # An account created through single sign-on has no password yet and
    # may set its first one without a current password.
    if oidc.has_password(user) and not verify_password(payload.current_password, user.password):
        rate_limit.record(db, rate_limit.PASSWORD_FAILURES_PER_USER, str(user.id))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    account_service.set_password(db, user, payload.new_password)
    revoke_user_sessions(db, user.id, keep_session_id=auth.session.id)
    db.commit()
    audit.log(AuditAction.PASSWORD_CHANGED, user_id=user.id)
    return {"message": "Password changed"}


@router.post("/password-reset")
def reset_password(payload: PasswordReset, request: Request, db: Session = Depends(get_db)):
    """Set a new password with a one-time link issued by an administrator."""
    ip = client_ip(request)
    rate_limit.check(db, rate_limit.LOGIN_FAILURES_PER_IP, ip)
    try:
        account_service.reset_password(db, payload.token, payload.new_password)
    except AccountError as exc:
        db.rollback()
        rate_limit.record(db, rate_limit.LOGIN_FAILURES_PER_IP, ip)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return {"message": "Password changed. Please sign in."}


@router.get("/me", response_model=UserSchema)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/verify-token", response_model=UserSchema)
def verify_token_endpoint(current_user: User = Depends(get_current_user)):
    """Endpoint to verify if the current token is valid"""
    return current_user


router.include_router(oidc.router)
