from sqlalchemy import Column, Float, ForeignKey, Integer, String, JSON, UniqueConstraint, Boolean
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class ReadingProgress(BaseModel):
    __tablename__ = "reading_progress"
    __table_args__ = (UniqueConstraint("user_id", "novel_id", name="uq_user_novel_progress"),)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=True)
    chapter_number = Column(Integer, nullable=True)
    chapter_key = Column(String(36), nullable=True)
    current_identity_inferred = Column(Boolean, nullable=False, default=False, server_default="0")
    furthest_chapter_key = Column(String(36), nullable=True)
    furthest_identity_inferred = Column(Integer, nullable=False, default=0, server_default="0")
    source_content_version = Column(String(64), nullable=True)
    furthest_content_version = Column(String(64), nullable=True)
    manifest_epoch = Column(String(36), nullable=True)
    manifest_revision = Column(String(20), nullable=True)
    position = Column(Integer, nullable=False, default=0, server_default="0")
    percent = Column(Float, nullable=False, default=0, server_default="0")
    revision = Column(Integer, nullable=False, default=0, server_default="0")
    furthest_chapter_number = Column(Integer, nullable=False, default=0, server_default="0")
    furthest_percent = Column(Float, nullable=False, default=0, server_default="0")
    block_id = Column(String(128), nullable=True)
    text_offset = Column(Integer, nullable=False, default=0, server_default="0")
    text_quote = Column(String(240), nullable=True)
    quote_prefix = Column(String(80), nullable=True)
    quote_suffix = Column(String(80), nullable=True)
    locator_content_version = Column(String(64), nullable=True)
    locator_variant = Column(String(128), nullable=True)
    device_id = Column(String(128), nullable=True)
    reading_run_key = Column(String(36), nullable=True)

    user = relationship("User")
    novel = relationship("Novel")
    chapter = relationship("Chapter")


class ReadingProgressOperation(BaseModel):
    __tablename__ = "reading_progress_operations"
    __table_args__ = (UniqueConstraint("user_id", "operation_id", name="uq_progress_user_operation"),)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    operation_id = Column(String(128), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    response = Column(JSON, nullable=False)
