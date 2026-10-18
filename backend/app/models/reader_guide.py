"""Account-private guide work; never shared catalog analysis."""
from sqlalchemy import BigInteger, Column, ForeignKey, Integer, String, JSON, Text, DateTime, UniqueConstraint, LargeBinary
from app.models.base import BaseModel


class PrivateGuideJob(BaseModel):
    __tablename__ = 'private_guide_jobs'
    __table_args__ = (UniqueConstraint('user_id', 'cache_key', name='uq_private_guide_result_cache'),)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    novel_id = Column(Integer, ForeignKey('novels.id', ondelete='CASCADE'), nullable=False, index=True)
    provider_id = Column(Integer, ForeignKey('reader_providers.id'), nullable=False)
    reading_run_key = Column(String(36), nullable=False)
    job_key = Column(String(36), nullable=False, unique=True)
    kind = Column(String(20), nullable=False)
    status = Column(String(24), nullable=False, default='queued')
    revision = Column(Integer, nullable=False, default=1)
    cache_key = Column(String(64), nullable=False, index=True)
    fingerprint = Column(String(64), nullable=False)
    review = Column(JSON, nullable=False)
    completed_steps = Column(Integer, nullable=False, default=0)
    total_steps = Column(Integer, nullable=False)
    retry_generation = Column(Integer, nullable=False, default=0)
    lease_owner = Column(String(36))
    lease_expires_at = Column(DateTime)
    error_code = Column(String(80))
    error = Column(Text)
    charged_microusd = Column(BigInteger, nullable=False, default=0)


class PrivateGuideArtifact(BaseModel):
    __tablename__ = 'private_guide_artifacts'
    __table_args__ = (UniqueConstraint('job_id', 'step', name='uq_private_guide_step'),)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    novel_id = Column(Integer, ForeignKey('novels.id', ondelete='CASCADE'), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey('private_guide_jobs.id', ondelete='CASCADE'), nullable=False)
    step = Column(Integer, nullable=False)
    kind = Column(String(20), nullable=False)
    content = Column(JSON, nullable=False)
    citations = Column(JSON, nullable=False)
    media_data = Column(LargeBinary)
    media_type = Column(String(80))


class PrivateGuideOperation(BaseModel):
    __tablename__ = 'private_guide_operations'
    __table_args__ = (UniqueConstraint('user_id', 'operation_id', name='uq_private_guide_operation'),)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    operation_id = Column(String(128), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    response = Column(JSON, nullable=False)
