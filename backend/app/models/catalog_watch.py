"""Private prepared catalog queries and once-per-work matching receipts."""
import secrets
from uuid import uuid4
from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint
from app.models.base import BaseModel


class CatalogWatch(BaseModel):
    __tablename__ = 'catalog_watches'
    __table_args__ = (UniqueConstraint('user_id', 'search_id', name='uq_catalog_watch_search'),)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    search_id = Column(Integer, ForeignKey('saved_searches.id', ondelete='CASCADE'), nullable=False, index=True)
    search_key = Column(String(36), nullable=False)
    account_key = Column(String(36), nullable=False)
    identity_key = Column(String(36), nullable=False, unique=True, default=lambda: str(uuid4()))
    revision = Column(String(64), nullable=False, default=lambda: secrets.token_hex(32))
    search_revision = Column(String(64), nullable=False)
    permission_fingerprint = Column(String(64), nullable=False)
    status = Column(String(24), nullable=False, default='prepared', index=True)
    mode = Column(String(16), nullable=False)
    prepared = Column(JSON, nullable=False)
    prepared_revision = Column(String(64), nullable=False)
    epoch = Column(String(36), nullable=False)
    cursor = Column(BigInteger, nullable=False, default=0)
    baseline = Column(JSON, nullable=True)
    baseline_total = Column(Integer, nullable=True)
    baseline_offset = Column(Integer, nullable=False, default=0)
    last_checked_at = Column(DateTime, nullable=True)
    reason = Column(String(64), nullable=True)
    lease_owner = Column(String(36), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)
    next_check_at = Column(DateTime, nullable=True)


class CatalogWatchSeen(BaseModel):
    __tablename__ = 'catalog_watch_seen'
    __table_args__ = (UniqueConstraint('watch_id', 'work_key', name='uq_catalog_watch_seen'),)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    watch_id = Column(Integer, ForeignKey('catalog_watches.id', ondelete='CASCADE'), nullable=False, index=True)
    work_key = Column(String(36), nullable=False)


class CatalogMatch(BaseModel):
    __tablename__ = 'catalog_matches'
    __table_args__ = (UniqueConstraint('watch_id', 'work_key', name='uq_catalog_match_work'),)
    user_id = Column(Integer, ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    watch_id = Column(Integer, ForeignKey('catalog_watches.id', ondelete='CASCADE'), nullable=False, index=True)
    work_key = Column(String(36), nullable=False)
    novel = Column(JSON, nullable=False)
    event_id = Column(Integer, ForeignKey('novel_update_events.id', ondelete='SET NULL'), nullable=True)
    read_at = Column(DateTime, nullable=True)
