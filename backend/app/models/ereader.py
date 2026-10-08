"""E-reader access: app passwords, built EPUB files, and KOReader progress.

E-readers cannot run the web sign-in, so each user creates app passwords for
them. The database stores only a bcrypt hash of the MD5 of the app password,
which is also what KOReader sends as its ``x-auth-key``.
"""

from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class AppPassword(BaseModel):
    __tablename__ = "app_passwords"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(120), nullable=False, default="")
    # "opds" for catalog and EPUB downloads, "kosync" for reading progress sync.
    scope = Column(String(20), nullable=False)
    secret_hash = Column(String(255), nullable=False)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)

    user = relationship("User")


class EpubBuild(BaseModel):
    """One generated EPUB of a novel. ``partial_md5`` is KOReader's document id
    for that exact file, so progress from any copy we ever served can be
    matched back to the novel."""

    __tablename__ = "epub_builds"
    __table_args__ = (UniqueConstraint("novel_id", "fingerprint", name="uq_epub_build_novel_fingerprint"),)

    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False, index=True)
    fingerprint = Column(String(64), nullable=False)
    partial_md5 = Column(String(32), nullable=False, index=True)
    size_bytes = Column(Integer, nullable=False)
    file_name = Column(String(255), nullable=False)
    # Chapter numbers in spine order; spine index N is KOReader's DocFragment[N+1].
    spine = Column(JSON, nullable=False, default=list)


class KosyncProgress(BaseModel):
    __tablename__ = "kosync_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "document", name="uq_kosync_progress_user_document"),
        Index("ix_kosync_progress_user_novel", "user_id", "novel_id"),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    document = Column(String(64), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    progress = Column(String(512), nullable=False, default="")
    percentage = Column(Float, nullable=False, default=0, server_default="0")
    device = Column(String(100), nullable=False, default="", server_default="")
    device_id = Column(String(100), nullable=False, default="", server_default="")
