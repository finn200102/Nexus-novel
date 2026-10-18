from sqlalchemy import JSON, event, select, Column, DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class ChapterDownloadJob(BaseModel):
    """Persistent request state for automatic and manual chapter downloads."""

    __tablename__ = "chapter_download_jobs"
    __table_args__ = (
        Index("ix_chapter_download_jobs_lease", "status", "lease_expires_at"),
        Index("uq_active_chapter_download", "user_id", "chapter_id", unique=True,
              sqlite_where=text("status IN ('queued', 'processing', 'retry_wait')"),
              postgresql_where=text("status IN ('queued', 'processing', 'retry_wait')")),
    )
    lease_owner = Column(String(255), nullable=True)
    lease_expires_at = Column(DateTime, nullable=True)

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    library_id = Column(Integer, ForeignKey("libraries.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    chapter_identity = Column(JSON, nullable=True)
    status = Column(String(20), nullable=False, default="queued", server_default="queued")
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    max_attempts = Column(Integer, nullable=False, default=3, server_default="3")
    next_attempt_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    last_attempt_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    cancellation_reason = Column(Text, nullable=True)
    error_code = Column(String(80), nullable=True)
    error = Column(Text, nullable=True)

    user = relationship("User")
    library = relationship("Library")
    novel = relationship("Novel")
    chapter = relationship("Chapter")



def download_identity(connection,*,chapter_id,novel_id,library_id,user_id):
    from app.models.chapter import Chapter
    from app.models.novel import Novel
    from app.models.library import Library
    from app.models.chapter_manifest import ChapterManifestState
    row=connection.execute(select(Chapter.chapter_key,Chapter.metadata_manifest_key,Chapter.metadata_chapter_key,
        Chapter.site_chapter_id,Chapter.source_url,Novel.metadata_id,ChapterManifestState.metadata_source,ChapterManifestState.manifest_epoch,ChapterManifestState.revision).join(
            Novel,Novel.id==Chapter.novel_id).join(Library,Library.id==Novel.library_id).join(
            ChapterManifestState,ChapterManifestState.novel_id==Novel.id).where(Chapter.id==chapter_id,
                Chapter.novel_id==novel_id,Novel.library_id==library_id,Library.user_id==user_id,Chapter.archived.is_(False))).first()
    if row is None or row.chapter_key is None:return None
    captured=dict(row._mapping);captured['manifest_revision']=str(captured.pop('revision'))
    return captured


@event.listens_for(ChapterDownloadJob,'before_insert')
def capture_download_identity(mapper,connection,target):
    captured=download_identity(connection,chapter_id=target.chapter_id,novel_id=target.novel_id,library_id=target.library_id,user_id=target.user_id)
    if captured is None:
        if target.chapter_identity is not None:raise ValueError('A download requires an owned active chapter lifecycle')
        # Preserve unresolved legacy/import records as unknown. Workers reject
        # these rows before dispatch; never guess an owner's current UUID.
        return
    if target.chapter_identity is not None and target.chapter_identity!=captured:raise ValueError('The queued download chapter identity changed')
    target.chapter_identity=captured
