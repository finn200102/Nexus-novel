from sqlalchemy import (
    Column,
    String,
    Text,
    Integer,
    BigInteger,
    ForeignKey,
    Enum,
    DateTime,
    JSON,
    Boolean,
    Index,
    text,
    FetchedValue,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from app.models.base import BaseModel
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
    document = Column(JSON, nullable=True)
    chapter_number = Column(Integer, nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id"))
    chapter_key = Column(String(36), nullable=True, server_default=FetchedValue())
    metadata_manifest_key = Column(String(36), nullable=True)
    metadata_chapter_key = Column(String(36), nullable=True)
    archived = Column(Boolean, nullable=False, default=False, server_default="0")
    archived_at = Column(DateTime, nullable=True)
    site_chapter_id = Column(BigInteger)
    source_url = Column(String(500))
    word_count = Column(Integer)
    novel = relationship("Novel", back_populates="chapters")
    versions = relationship("ChapterVersion", back_populates="chapter", cascade="all, delete-orphan")
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
        UniqueConstraint("chapter_key", name="uq_chapter_lifecycle_key"),
        Index("uq_active_chapter_novel_number", "novel_id", "chapter_number", unique=True,
              sqlite_where=text("archived = 0"), postgresql_where=text("archived = false")),
    )

    @property
    def manifest_epoch(self):
        return self.novel.manifest_state.manifest_epoch if self.novel and self.novel.manifest_state else None

    @property
    def manifest_revision(self):
        return str(self.novel.manifest_state.revision) if self.novel and self.novel.manifest_state else None

    def __repr__(self):
        return f"<Chapter {self.title} - #{self.chapter_number}>"
