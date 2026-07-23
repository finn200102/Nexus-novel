from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint, func

from app.models.base import BaseModel


class MetadataWebhookDelivery(BaseModel):
    """Receipt for a metadata source job delivery.

    The unique delivery key is claimed in the same transaction as the user
    update events and download jobs. This makes retries safe: a concurrent or
    repeated delivery can observe the committed receipt and become a no-op.
    """

    __tablename__ = "metadata_webhook_deliveries"
    __table_args__ = (
        UniqueConstraint("delivery_key", name="uq_metadata_webhook_delivery_key"),
    )

    delivery_key = Column(String(512), nullable=False)
    source_job_id = Column(String(255), nullable=False)
    source_id = Column(Integer, nullable=False)
    event_type = Column(String(80), nullable=False)
    claimed_at = Column(DateTime, nullable=False, server_default=func.now())
