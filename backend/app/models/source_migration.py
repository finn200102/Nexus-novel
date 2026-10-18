"""Private, reviewable reading continuity transfers; never source content merges."""
from sqlalchemy import Column, ForeignKey, Integer, JSON, String, DateTime, UniqueConstraint
from app.models.base import BaseModel


class SourceMigration(BaseModel):
    __tablename__ = 'source_migrations'
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    source_novel_id = Column(Integer, ForeignKey('novels.id', ondelete='SET NULL'), nullable=True, index=True)
    target_novel_id = Column(Integer, ForeignKey('novels.id', ondelete='SET NULL'), nullable=True, index=True)
    revision = Column(Integer, nullable=False, default=1, server_default='1')
    status = Column(String(20), nullable=False, default='applied', server_default='applied')
    plan = Column(JSON, nullable=False)
    counts = Column(JSON, nullable=False)
    created_rows = Column(JSON, nullable=False)
    target_guard = Column(String(64), nullable=False)
    undone_at = Column(DateTime, nullable=True)


class SourceMigrationOperation(BaseModel):
    __tablename__ = 'source_migration_operations'
    __table_args__ = (UniqueConstraint('user_id', 'operation_id', name='uq_source_migration_operation'),)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    migration_id = Column(Integer, ForeignKey('source_migrations.id', ondelete='CASCADE'), nullable=False, index=True)
    operation_id = Column(String(128), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    response = Column(JSON, nullable=False)
