from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class ImportJob(BaseModel):
    """A durable request to bring many stories into one library.

    ``source`` is url_list, epub, ao3_bookmarks, ffn_favorites, rr_list or
    user_data (missing novels of a /me/import). List sources (AO3 bookmarks)
    are expanded page by page by the worker; ``next_page`` is the cursor.
    """

    __tablename__ = "import_jobs"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    library_id = Column(Integer, ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False)
    source = Column(String(32), nullable=False)
    params = Column(JSON, nullable=True)
    status = Column(String(20), nullable=False, default="queued", server_default="queued")
    next_page = Column(Integer, nullable=True)
    total_items = Column(Integer, nullable=False, default=0, server_default="0")
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    error = Column(Text, nullable=True)

    items = relationship("ImportJobItem", back_populates="job", cascade="all, delete-orphan", order_by="ImportJobItem.position")


class ImportJobItem(BaseModel):
    """One story of an import job and its outcome.

    Final statuses: linked (added to the library), duplicate (already there
    or listed twice), unsupported (not a story URL Nexus can read) and
    failed (with ``reason``).
    """

    __tablename__ = "import_job_items"
    __table_args__ = (Index("ix_import_job_items_job_status", "job_id", "status"),)

    job_id = Column(Integer, ForeignKey("import_jobs.id", ondelete="CASCADE"), nullable=False)
    position = Column(Integer, nullable=False)
    url = Column(String(500), nullable=True)
    label = Column(String(500), nullable=True)
    title = Column(String(500), nullable=True)
    status = Column(String(20), nullable=False, default="queued", server_default="queued")
    reason = Column(Text, nullable=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="SET NULL"), nullable=True)

    job = relationship("ImportJob", back_populates="items")
