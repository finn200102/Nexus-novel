from sqlalchemy import Column, ForeignKey, Integer, Text, UniqueConstraint

from app.models.base import BaseModel


class ReadwiseConnection(BaseModel):
    """A user's Readwise access token, stored encrypted (see notification_crypto)."""

    __tablename__ = "readwise_connections"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_readwise_connection_user"),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_encrypted = Column(Text, nullable=False)
