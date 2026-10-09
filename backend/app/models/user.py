from sqlalchemy import Boolean, Column, DateTime, Index, String, UniqueConstraint, text
from sqlalchemy.orm import relationship
from app.models.base import BaseModel

class User(BaseModel):
    __tablename__ = "users"
    # Usernames are unique regardless of case; signup and login compare
    # lower(username).
    __table_args__ = (
        Index("ux_users_username_lower", text("lower(username)"), unique=True),
        UniqueConstraint("oidc_issuer", "oidc_subject", name="uq_users_oidc_identity"),
    )

    username = Column(String(100), nullable=False, index=True)
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

    libraries = relationship("Library", back_populates="user")

    def __repr__(self):
        return f"<User {self.username}>"
