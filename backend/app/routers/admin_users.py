"""Administrator user management, sign-up policy and invites."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.audit import AuditAction, audit
from app.auth.dependencies import require_admin
from app.auth.sessions import revoke_user_sessions, utcnow
from app.models.account import InviteCode, UserSession
from app.models.user import User
from app.schemas.user import (
    AdminUser,
    ContentLimits,
    AdminUserUpdate,
    InstanceSettings,
    Invite,
    InviteCreate,
    PasswordResetLink,
    PasswordResetLinkRequest,
)
from app.services import account_service, content_limit_service
from app.services.account_service import AccountError
from config.database import get_db

router = APIRouter(prefix="/admin", tags=["admin-users"])


def _get_user(db: Session, user_id: int) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


def _bad_request(exc: AccountError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _admin_user(user: User, last_seen_at=None, active_sessions: int = 0) -> AdminUser:
    return AdminUser(
        id=user.id,
        username=user.username,
        is_admin=bool(user.is_admin),
        is_disabled=bool(user.is_disabled),
        created_at=user.created_at,
        last_seen_at=last_seen_at,
        active_sessions=active_sessions,
        content_limits=content_limit_service.describe(user),
    )


def _invite(invite: InviteCode, code: str | None = None) -> Invite:
    return Invite(
        id=invite.id,
        label=invite.label,
        max_uses=invite.max_uses,
        use_count=invite.use_count,
        expires_at=invite.expires_at,
        revoked_at=invite.revoked_at,
        created_at=invite.created_at,
        status=account_service.invite_status(invite),
        code=code,
    )


@router.get("/users", response_model=list[AdminUser])
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    sessions = {
        user_id: (last_seen, count)
        for user_id, last_seen, count in db.query(
            UserSession.user_id, func.max(UserSession.last_seen_at), func.count(UserSession.id)
        )
        .filter(UserSession.revoked_at.is_(None))
        .group_by(UserSession.user_id)
    }
    users = db.query(User).order_by(User.id.asc()).all()
    return [_admin_user(user, *sessions.get(user.id, (None, 0))) for user in users]


@router.patch("/users/{user_id}", response_model=AdminUser)
def update_user(
    user_id: int,
    payload: AdminUserUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = _get_user(db, user_id)
    if payload.is_disabled and user.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot disable your own account.")
    removes_admin = (payload.is_admin is False and user.is_admin) or (payload.is_disabled and not user.is_disabled)
    if removes_admin:
        try:
            account_service.ensure_admin_remains(db, user)
        except AccountError as exc:
            raise _bad_request(exc) from exc
    if payload.is_admin is not None:
        user.is_admin = payload.is_admin
    if payload.is_disabled is not None:
        user.is_disabled = payload.is_disabled
        if payload.is_disabled:
            revoke_user_sessions(db, user.id)
    db.commit()
    db.refresh(user)
    audit.log(
        AuditAction.USER_UPDATED,
        user_id=admin.id,
        details={"target_user_id": user.id, **payload.model_dump(exclude_none=True)},
    )
    return _admin_user(user)


@router.put("/users/{user_id}/content-limits", response_model=AdminUser)
def set_content_limits(
    user_id: int,
    payload: ContentLimits,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Set a household profile's maximum content rating, blocked tags and unrated handling."""
    user = _get_user(db, user_id)
    user.max_content_rating = payload.max_content_rating
    user.hide_unrated = payload.hide_unrated
    user.blocked_tags = content_limit_service.clean_blocked_tags(payload.blocked_tags) or None
    db.commit()
    db.refresh(user)
    audit.log(
        AuditAction.USER_UPDATED,
        user_id=admin.id,
        details={"target_user_id": user.id, "content_limits": content_limit_service.describe(user)},
    )
    return _admin_user(user)


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = _get_user(db, user_id)
    if user.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account.")
    try:
        account_service.ensure_admin_remains(db, user)
    except AccountError as exc:
        raise _bad_request(exc) from exc
    account_service.delete_user_account(db, user)
    audit.log(AuditAction.USER_DELETED, user_id=admin.id, details={"target_user_id": user_id})


@router.post("/users/{user_id}/password-reset", response_model=PasswordResetLink)
def issue_password_reset(
    user_id: int,
    payload: PasswordResetLinkRequest | None = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Issue a one-time link the administrator passes on to the user."""
    user = _get_user(db, user_id)
    hours = (payload or PasswordResetLinkRequest()).expires_in_hours
    reset, token = account_service.create_password_reset(db, user, admin, hours)
    audit.log(AuditAction.PASSWORD_RESET_ISSUED, user_id=admin.id, details={"target_user_id": user.id})
    return PasswordResetLink(token=token, path=f"/reset-password?token={token}", expires_at=reset.expires_at)


@router.get("/settings", response_model=InstanceSettings)
def get_settings(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return InstanceSettings(signup_mode=account_service.get_signup_mode(db))


@router.put("/settings", response_model=InstanceSettings)
def update_settings(payload: InstanceSettings, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        account_service.set_signup_mode(db, payload.signup_mode)
    except AccountError as exc:
        raise _bad_request(exc) from exc
    db.commit()
    audit.log(AuditAction.INSTANCE_SETTINGS_CHANGED, user_id=admin.id, details=payload.model_dump())
    return InstanceSettings(signup_mode=account_service.get_signup_mode(db))


@router.get("/invites", response_model=list[Invite])
def list_invites(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [_invite(invite) for invite in db.query(InviteCode).order_by(InviteCode.id.desc()).all()]


@router.post("/invites", response_model=Invite, status_code=status.HTTP_201_CREATED)
def create_invite(payload: InviteCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    invite, code = account_service.create_invite(
        db, admin, payload.label, payload.max_uses, payload.expires_in_days
    )
    audit.log(AuditAction.INVITE_CREATED, user_id=admin.id, details={"invite_id": invite.id})
    return _invite(invite, code)


@router.delete("/invites/{invite_id}", response_model=Invite)
def revoke_invite(invite_id: int, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    invite = db.get(InviteCode, invite_id)
    if invite is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
    if invite.revoked_at is None:
        invite.revoked_at = utcnow()
        db.commit()
        db.refresh(invite)
        audit.log(AuditAction.INVITE_REVOKED, user_id=admin.id, details={"invite_id": invite.id})
    return _invite(invite)
