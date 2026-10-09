from sqlalchemy import Column, DateTime, ForeignKey, Integer, String

from app.models.base import BaseModel


class UserFeedToken(BaseModel):
    """The secret token in a user's personal Atom feed URL.

    Only ``sha256(token)`` is stored. The token is random and high-entropy, so
    a fast hash is enough and lets the feed look the row up directly.
    """

    __tablename__ = "user_feed_tokens"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    token_hash = Column(String(64), nullable=False, unique=True)
    last_used_at = Column(DateTime, nullable=True)
