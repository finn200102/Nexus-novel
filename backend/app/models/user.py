from sqlalchemy import JSON, Boolean, Column, DateTime, Index, String, UniqueConstraint, text, true
from sqlalchemy.orm import relationship
from app.models.base import BaseModel
from uuid import uuid4

class User(BaseModel):
    __tablename__ = "users"
    # Usernames are unique regardless of case; signup and login compare
    # lower(username).
    __table_args__ = (
        Index("ux_users_username_lower", text("lower(username)"), unique=True),
        UniqueConstraint("oidc_issuer", "oidc_subject", name="uq_users_oidc_identity"),
    )

    username = Column(String(100), nullable=False, index=True)
    storage_id = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid4()))
    # Empty for accounts that only sign in through single sign-on.
    password = Column(String(255), nullable=False, index=True)
    is_admin = Column(Boolean, nullable=False, default=False, server_default="0")
    # A disabled account cannot sign in and its sessions stop working.
    is_disabled = Column(Boolean, nullable=False, default=False, server_default="0")
    password_changed_at = Column(DateTime, nullable=True)
    # Single sign-on identity: the provider's issuer and its stable subject
    # id. Accounts are linked by this pair only, never by e-mail.
    oidc_issuer = Column(String(255), nullable=True)
    oidc_subject = Column(String(255), nullable=True)
    # Content limits set by an administrator (household profiles). A null
    # rating means no rating limit; blocked tags apply either way.
    max_content_rating = Column(String(16), nullable=True)
    blocked_tags = Column(JSON, nullable=True)
    # For a rating-limited profile: hide works whose rating is unknown.
    hide_unrated = Column(Boolean, nullable=False, default=True, server_default=true())

    libraries = relationship("Library", back_populates="user")

    def __repr__(self):
        return f"<User {self.username}>"
