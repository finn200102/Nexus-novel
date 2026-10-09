from sqlalchemy import Column, Date, ForeignKey, Integer, UniqueConstraint

from app.models.base import BaseModel


class ReadingSessionDaily(BaseModel):
    """Reading time, words and finished chapters per user, novel and day (reading stats v1)."""

    __tablename__ = "reading_sessions_daily"
    __table_args__ = (UniqueConstraint("user_id", "day", "novel_id", name="uq_reading_sessions_daily"),)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    day = Column(Date, nullable=False, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    seconds = Column(Integer, nullable=False, default=0, server_default="0")
    words = Column(Integer, nullable=False, default=0, server_default="0")
    chapters_finished = Column(Integer, nullable=False, default=0, server_default="0")
