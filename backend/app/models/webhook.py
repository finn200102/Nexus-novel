from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class Webhook(BaseModel):
    """An outgoing HTTP endpoint that receives released update events."""

    __tablename__ = "webhooks"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    url_encrypted = Column(Text, nullable=False)
    url_hint = Column(String(255), nullable=False, default="", server_default="")
    # Encrypted at rest because it is needed to sign every request.
    secret_encrypted = Column(Text, nullable=True)
    event_types = Column(JSON, nullable=False, default=list)
    enabled = Column(Boolean, nullable=False, default=True, server_default="1")
    last_status_code = Column(Integer, nullable=True)
    last_error = Column(String(255), nullable=True)
    last_delivered_at = Column(DateTime, nullable=True)
    consecutive_failures = Column(Integer, nullable=False, default=0, server_default="0")

    user = relationship("User")


class WebhookDelivery(BaseModel):
    """Receipt for one event sent to one webhook. Unique per pair, so an
    event is never posted twice to the same endpoint."""

    __tablename__ = "webhook_deliveries"
    __table_args__ = (UniqueConstraint("webhook_id", "event_id", name="uq_webhook_delivery_event"),)

    webhook_id = Column(Integer, ForeignKey("webhooks.id", ondelete="CASCADE"), nullable=False, index=True)
    event_id = Column(Integer, ForeignKey("novel_update_events.id", ondelete="CASCADE"), nullable=False)
    status_code = Column(Integer, nullable=True)
    error = Column(String(255), nullable=True)
