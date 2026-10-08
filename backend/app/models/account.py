"""Account state: sign-in sessions, invites, password resets, rate limits.

Secrets handed to a browser or an admin (refresh tokens, invite codes, reset
links) are only stored as SHA-256 hashes, so a database dump cannot be used to
sign in.
"""

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class InstanceSetting(BaseModel):
    """Instance-wide settings an administrator can change at runtime."""

    __tablename__ = "instance_settings"

    key = Column(String(80), nullable=False, unique=True)
    value = Column(Text, nullable=False)


class UserSession(BaseModel):
    """One signed-in device. Access tokens carry its id and stop working once
    it is revoked; its refresh tokens rotate on every use."""

    __tablename__ = "user_sessions"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    last_seen_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    user_agent = Column(String(255), nullable=True)
    ip_address = Column(String(64), nullable=True)

    user = relationship("User")


class RefreshToken(BaseModel):
    __tablename__ = "refresh_tokens"

    session_id = Column(Integer, ForeignKey("user_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    expires_at = Column(DateTime, nullable=False)
    # Set when the token is exchanged for its successor. Presenting a rotated
    # token again (outside a short grace period) revokes the whole session.
    rotated_at = Column(DateTime, nullable=True)

    session = relationship("UserSession")


class InviteCode(BaseModel):
    __tablename__ = "invite_codes"

    code_hash = Column(String(64), nullable=False, unique=True)
    label = Column(String(120), nullable=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # NULL means unlimited uses until expiry or revocation.
    max_uses = Column(Integer, nullable=True)
    use_count = Column(Integer, nullable=False, default=0, server_default="0")
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)


class PasswordResetToken(BaseModel):
    __tablename__ = "password_reset_tokens"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    created_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)


class AuthAttempt(BaseModel):
    """A counted sign-in or sign-up attempt, keyed like ``login:ip:<addr>``.

    Kept in the database so limits survive restarts and apply to every API
    process.
    """

    __tablename__ = "auth_attempts"
    __table_args__ = (Index("ix_auth_attempts_key_created", "key", "created_at"),)

    key = Column(String(255), nullable=False)
