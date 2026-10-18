"""One logical reading may continue across several private story copies."""
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, false
from app.models.base import BaseModel


class ReadingContinuity(BaseModel):
    __tablename__ = 'reading_continuities'
    continuity_key = Column(String(36), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    work_key = Column(String(36), nullable=False, index=True)
    logical_ordinal = Column(Integer, nullable=False)
    completed = Column(Boolean, nullable=False, default=False, server_default=false())
    completed_at = Column(DateTime)
    completed_at_inferred = Column(Boolean, nullable=False, default=False, server_default=false())
    completion_novel_id = Column(Integer, ForeignKey('novels.id', ondelete='SET NULL'))
