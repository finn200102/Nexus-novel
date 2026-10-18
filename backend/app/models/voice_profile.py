"""Private voice references; originals and generated previews stay account-owned."""
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, LargeBinary, String, Text
from app.models.base import BaseModel


class VoiceProfile(BaseModel):
    __tablename__ = "voice_profiles"
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    language = Column(String(32), nullable=False)
    sample = Column(LargeBinary, nullable=False)
    excerpt_start_seconds = Column(Float, nullable=True)
    excerpt_duration_seconds = Column(Float, nullable=True)
    transcript = Column(Text, nullable=False, default="")
    preview = Column(LargeBinary)
    model = Column(String(255), nullable=False)
    status = Column(String(20), nullable=False, default="queued", server_default="queued")
    lease_owner = Column(String(255))
    lease_expires_at = Column(DateTime)
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    max_attempts = Column(Integer, nullable=False, default=3, server_default="3")
    next_attempt_at = Column(DateTime)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    error_code = Column(String(80))
    error = Column(Text)
