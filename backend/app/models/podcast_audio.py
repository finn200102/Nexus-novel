"""Compatible private podcast audio, derived only from completed narration."""
from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from app.models.base import BaseModel


class PodcastAudioJob(BaseModel):
    __tablename__ = "podcast_audio_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "source_audio_job_id", "pipeline_version", name="uq_podcast_audio_source"),
        Index("ix_podcast_audio_queue", "status", "next_attempt_at", "created_at"),
        Index("ix_podcast_audio_lease", "status", "lease_expires_at"),
    )
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    source_audio_job_id = Column(Integer, ForeignKey("chapter_audio_jobs.id", ondelete="CASCADE"), nullable=False)
    chapter_number = Column(Integer, nullable=False)
    pipeline_version = Column(String(80), nullable=False)
    source_snapshot = Column(JSON, nullable=False)
    status = Column(String(20), nullable=False, default="queued", server_default="queued")
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
