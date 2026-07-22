from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class UserNovelFollow(BaseModel):
    """User-owned state for a novel in the Phase 1 follow pipeline."""

    __tablename__ = "user_novel_follows"
    __table_args__ = (
        UniqueConstraint("user_id", "novel_id", name="uq_user_novel_follow"),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    state = Column(String(20), nullable=False, default="plan_to_read", server_default="plan_to_read")
    followed_at = Column(DateTime, nullable=True)
    download_policy = Column(String(20), nullable=False, default="none", server_default="none")
    download_count = Column(Integer, nullable=False, default=0, server_default="0")
    notification_policy = Column(String(20), nullable=False, default="immediate", server_default="immediate")

    user = relationship("User")
    novel = relationship("Novel")
