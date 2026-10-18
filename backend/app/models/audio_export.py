"""Private audiobook exports with immutable narration selections."""
from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from app.models.base import BaseModel


class AudioExportJob(BaseModel):
    __tablename__ = "audio_export_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "novel_id", "fingerprint", name="uq_audio_export_selection"),
        Index("ix_audio_export_queue", "status", "next_attempt_at", "created_at"),
        Index("ix_audio_export_lease", "status", "lease_expires_at"),
    )
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    title = Column(String(255), nullable=False)
    chapters = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False, default="queued", server_default="queued")
    total_chapters = Column(Integer, nullable=False)
    completed_chapters = Column(Integer, nullable=False, default=0, server_default="0")
    audio_path = Column(String(1000), nullable=True)
    audio_bytes = Column(BigInteger, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    lease_owner = Column(String(255), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    max_attempts = Column(Integer, nullable=False, default=3, server_default="3")
    next_attempt_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error_code = Column(String(80), nullable=True)
    error = Column(Text, nullable=True)
