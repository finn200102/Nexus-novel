from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class ChapterAudioJob(BaseModel):
    """Durable, server-owned chapter narration job.

    Browser-owned jobs stay in IndexedDB for local-only endpoints.  This model
    is deliberately separate so a remote/self-hosted provider can keep working
    after the reader tab has closed.
    """

    __tablename__ = "chapter_audio_jobs"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    library_id = Column(Integer, ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(20), nullable=False, default="queued", server_default="queued")
    provider_id = Column(String(80), nullable=False)
    provider_url = Column(String(1000), nullable=False)
    provider_model = Column(String(255), nullable=False)
    provider_voice = Column(String(255), nullable=False)
    provider_language = Column(String(64), nullable=True)
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
    status = Column(String(20), nullable=False, default="queued", server_default="queued")
    audio_path = Column(String(1000), nullable=True)
    error = Column(Text, nullable=True)

    job = relationship("ChapterAudioJob")

    __table_args__ = (UniqueConstraint("job_id", "part_index", name="uq_audio_job_part"),)
