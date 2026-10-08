from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class PushSubscription(BaseModel):
    """A browser or device that accepted Web Push for this account."""

    __tablename__ = "push_subscriptions"
    __table_args__ = (UniqueConstraint("endpoint", name="uq_push_subscription_endpoint"),)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    endpoint = Column(String(2048), nullable=False)
    p256dh = Column(String(255), nullable=False)
    auth = Column(String(64), nullable=False)
    user_agent = Column(String(255), nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    failure_count = Column(Integer, nullable=False, default=0, server_default="0")

    user = relationship("User")


class NotificationChannel(BaseModel):
    """An Apprise destination. The URL is encrypted; only a hint is ever shown."""

    __tablename__ = "notification_channels"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(20), nullable=False, default="apprise", server_default="apprise")
    url_encrypted = Column(Text, nullable=False)
    url_hint = Column(String(255), nullable=False, default="", server_default="")
    label = Column(String(120), nullable=False, default="", server_default="")
    enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    last_error = Column(String(255), nullable=True)

    user = relationship("User")
