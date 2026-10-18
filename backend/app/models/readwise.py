from uuid import uuid4
from sqlalchemy import String, FetchedValue, Index
from app.models.export_lifecycle import register
from sqlalchemy import Column, ForeignKey, Integer, Text, UniqueConstraint

from app.models.base import BaseModel


class ReadwiseConnection(BaseModel):
    """A user's Readwise access token, stored encrypted (see notification_crypto)."""

    __tablename__ = "readwise_connections"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_readwise_connection_user"),
        Index("uq_readwise_connections_export_key", "export_key", unique=True),
    )

    export_key = Column(String(36), nullable=True, default=lambda: str(uuid4()), server_default=FetchedValue())

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_encrypted = Column(Text, nullable=False)


register(ReadwiseConnection.__table__)
