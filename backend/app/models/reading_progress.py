from sqlalchemy import Column, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class ReadingProgress(BaseModel):
    __tablename__ = "reading_progress"
    __table_args__ = (UniqueConstraint("user_id", "novel_id", name="uq_user_novel_progress"),)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True)
    chapter_number = Column(Integer, nullable=True)
    position = Column(Integer, nullable=False, default=0, server_default="0")
    percent = Column(Float, nullable=False, default=0, server_default="0")

    user = relationship("User")
    novel = relationship("Novel")
    chapter = relationship("Chapter")
