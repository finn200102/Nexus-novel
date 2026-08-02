from sqlalchemy import Column, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class ReadingHistory(BaseModel):
    """One durable, device-safe reading event per user/chapter/day."""

    __tablename__ = "reading_history"
    __table_args__ = (UniqueConstraint("user_id", "novel_id", "chapter_number", "reading_date", name="uq_reading_history_day"),)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_number = Column(Integer, nullable=False)
    reading_date = Column(DateTime, nullable=False)
    max_percent = Column(Integer, nullable=False, default=0)

    user = relationship("User")
    novel = relationship("Novel")
