"""A revocable credential scoped to one owner's story recordings."""
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from app.models.base import BaseModel


class PodcastFeedToken(BaseModel):
    __tablename__ = "podcast_feed_tokens"
    __table_args__ = (UniqueConstraint("user_id", "novel_id", name="uq_podcast_owner_story"),)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(64), nullable=False, unique=True)
    last_used_at = Column(DateTime, nullable=True)
