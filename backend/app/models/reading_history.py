from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Boolean, Index, text
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class ReadingHistory(BaseModel):
    """One durable, device-safe reading point per user/run/chapter/day."""

    __tablename__ = "reading_history"
    __table_args__ = (
        Index("uq_reading_history_identity_day_run", "user_id", "novel_id", "chapter_key", "reading_date", "reading_run_key", unique=True,
              sqlite_where=text("chapter_key IS NOT NULL"), postgresql_where=text("chapter_key IS NOT NULL")),
        Index("uq_reading_history_unbound_day_run", "user_id", "novel_id", "chapter_number", "reading_date", "reading_run_key", unique=True,
              sqlite_where=text("chapter_key IS NULL"), postgresql_where=text("chapter_key IS NULL")),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_number = Column(Integer, nullable=False)
    chapter_key = Column(String(36), nullable=True)
    identity_inferred = Column(Boolean, nullable=False, default=False, server_default="0")
    verified_content_version = Column(String(64), nullable=True)
    verified_percent = Column(Integer, nullable=False, default=0, server_default="0")
    reading_date = Column(DateTime, nullable=False)
    max_percent = Column(Integer, nullable=False, default=0)
    reading_run_key = Column(String(36), nullable=True)

    user = relationship("User")
    novel = relationship("Novel")
