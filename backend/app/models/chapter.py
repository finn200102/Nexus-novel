from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    BigInteger,
    ForeignKey,
    Enum,
    DateTime,
)
from sqlalchemy.orm import relationship
from app.models.base import BaseModel
from sqlalchemy import UniqueConstraint
import enum


class ContentStatus(enum.Enum):
    MISSING = "MISSING"
    PRESENT = "PRESENT"
    PROCESSING = "PROCESSING"
    FAILED = "FAILED"


class AudioStatus(enum.Enum):
    MISSING = "MISSING"
    PRESENT = "PRESENT"
    PROCESSING = "PROCESSING"
    FAILED = "FAILED"


class Chapter(BaseModel):
    __tablename__ = "chapters"

    title = Column(String(255))
    content = Column(Text)
    chapter_number = Column(Integer, nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id"))
    site_chapter_id = Column(BigInteger)
    source_url = Column(String(500))
    word_count = Column(Integer)
    novel = relationship("Novel", back_populates="chapters")
    content_status = Column(
        Enum(ContentStatus), default=ContentStatus.MISSING, nullable=False
    )
    audio_status = Column(
        Enum(AudioStatus), default=AudioStatus.MISSING, nullable=False
    )
    download_started_at = Column(DateTime, nullable=True)
    download_finished_at = Column(DateTime, nullable=True)
    download_error = Column(String(1000), nullable=True)
    retry_count = Column(Integer, default=0, nullable=False)
    category = Column(String(32), default="story", server_default="story", nullable=False)

    __table_args__ = (
        UniqueConstraint("novel_id", "chapter_number", name="uix_chapter_novel_number"),
    )

    def __repr__(self):
        return f"<Chapter {self.title} - #{self.chapter_number}>"
