from sqlalchemy import Boolean, Float, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, text, false
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class ChapterAudioJob(BaseModel):
    """Durable, server-owned chapter narration job.

    Browser-owned jobs stay in IndexedDB for local-only endpoints.  This model
    is deliberately separate so a remote/self-hosted provider can keep working
    after the reader tab has closed.
    """

    __tablename__ = "chapter_audio_jobs"
    __table_args__ = (
        Index("ix_audio_jobs_queue", "status", "next_attempt_at", "created_at"),
        Index("ix_chapter_audio_jobs_lease", "status", "lease_expires_at"),
        Index("uq_active_chapter_audio", "user_id", "chapter_id", unique=True,
              sqlite_where=text("status IN ('queued', 'processing', 'retry_wait')"),
              postgresql_where=text("status IN ('queued', 'processing', 'retry_wait')")),
    )
    lease_owner = Column(String(255), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    library_id = Column(Integer, ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), nullable=False, default="queued", server_default="queued")
    voice_profile_id = Column(Integer, ForeignKey("voice_profiles.id", ondelete="SET NULL"), nullable=True)
    source_version = Column(String(64), nullable=True)
    chapter_key = Column(String(36), nullable=True)
    manifest_epoch = Column(String(36), nullable=True)
    manifest_revision = Column(String(64), nullable=True)
    chapter_title_snapshot = Column(Text, nullable=True)
    chapter_number_snapshot = Column(Integer, nullable=True)
    identity_inferred = Column(Boolean, nullable=False, default=False, server_default=false())
    include_author_notes = Column(Boolean, nullable=True)
    pronunciation_version = Column(String(64), nullable=True)
    pronunciation_rules = Column(JSON, nullable=True)
    preparation = Column(JSON, nullable=True)
    preparation_version = Column(String(64), nullable=True)
    provider_id = Column(String(80), nullable=False)
    provider_url = Column(String(1000), nullable=False)
    provider_model = Column(String(255), nullable=False)
    provider_voice = Column(String(255), nullable=False)
    provider_language = Column(String(64), nullable=True)
    qwen_chunk_size = Column(Integer, nullable=True)
    generation_token_limit = Column(Integer, nullable=True)
    total_parts = Column(Integer, nullable=False, default=0, server_default="0")
    completed_parts = Column(Integer, nullable=False, default=0, server_default="0")
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    max_attempts = Column(Integer, nullable=False, default=3, server_default="3")
    next_attempt_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    error_code = Column(String(80), nullable=True)
    error = Column(Text, nullable=True)
    audio_path = Column(String(1000), nullable=True)
    audio_bytes = Column(Integer, nullable=True)

    user = relationship("User")
    library = relationship("Library")
    novel = relationship("Novel")
    chapter = relationship("Chapter")

class ChapterAudioPart(BaseModel):
    __tablename__ = "chapter_audio_parts"

    job_id = Column(Integer, ForeignKey("chapter_audio_jobs.id", ondelete="CASCADE"), nullable=False)
    part_index = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    synthesis_text = Column(Text, nullable=True)
    block_id = Column(String(100), nullable=True)
    text_offset = Column(Integer, nullable=True)
    text_length = Column(Integer, nullable=True)
    source_spans = Column(JSON, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    status = Column(String(20), nullable=False, default="queued", server_default="queued")
    audio_path = Column(String(1000), nullable=True)
    error = Column(Text, nullable=True)

    job = relationship("ChapterAudioJob")

    __table_args__ = (UniqueConstraint("job_id", "part_index", name="uq_audio_job_part"),)
