from sqlalchemy import Column, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class ChapterDownloadJob(BaseModel):
    """Persistent request state for automatic and manual chapter downloads."""

    __tablename__ = "chapter_download_jobs"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    library_id = Column(Integer, ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), nullable=False, default="queued", server_default="queued")
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    error = Column(Text, nullable=True)

    user = relationship("User")
    library = relationship("Library")
    novel = relationship("Novel")
    chapter = relationship("Chapter")
