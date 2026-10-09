from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class ReadingAnnotation(BaseModel):
    __tablename__ = "reading_annotations"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    annotation_type = Column(String(20), nullable=False, default="bookmark", server_default="bookmark")
    position = Column(Integer, nullable=False, default=0, server_default="0")
    percent = Column(Float, nullable=False, default=0, server_default="0")
    quote = Column(Text, nullable=True)
    note = Column(Text, nullable=True)
    # Set once the annotation has been pushed to Readwise; keeps syncs idempotent.
    exported_at = Column(DateTime, nullable=True)

    user = relationship("User")
    novel = relationship("Novel")
    chapter = relationship("Chapter")
