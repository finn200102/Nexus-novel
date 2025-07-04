from sqlalchemy import Column, String, Text, Integer, ForeignKey, Table, Boolean, Enum
from sqlalchemy.orm import relationship
from app.models.base import BaseModel
from sqlalchemy import UniqueConstraint
import enum

class ContentStatus(enum.Enum):
    MISSING = "MISSING"
    PRESENT = "PRESENT"
    PROCESSING = "PROCESSING"

class Chapter(BaseModel):
    __tablename__ = "chapters"

    title = Column(String(255))
    content = Column(Text)
    chapter_number = Column(Integer, nullable=False)
    novel_id = Column(Integer, ForeignKey('novels.id'))
    site_chapter_id = Column(Integer)
    novel = relationship("Novel", back_populates="chapters")
    content_status = Column(Enum(ContentStatus), default=ContentStatus.MISSING, nullable=False)

    __table_args__ = (
        UniqueConstraint('novel_id', 'chapter_number', name='uix_chapter_novel_number'),
    )

    def __repr__(self):
        return f"<Chapter {self.title} - #{self.chapter_number}>"
