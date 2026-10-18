from sqlalchemy import Column, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, event, select
from sqlalchemy.orm import relationship
from app.models.base import BaseModel


class ChapterVersion(BaseModel):
    """Private immutable originals retained when a source replaces a chapter."""
    __tablename__ = "chapter_versions"
    __table_args__ = (UniqueConstraint("chapter_key", "content_version", name="uq_chapter_identity_version"),)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    chapter_key = Column(String(36), nullable=True)
    content_version = Column(String(64), nullable=False)
    title = Column(String(255), nullable=True)
    source_url = Column(String(500), nullable=True)
    content = Column(Text, nullable=False)
    document = Column(JSON, nullable=False)
    byte_count = Column(Integer, nullable=False)
    reason = Column(String(32), nullable=False)
    chapter = relationship("Chapter", back_populates="versions")


@event.listens_for(ChapterVersion,'before_insert')
def bind_version_identity(mapper,connection,target):
    from app.models.chapter import Chapter
    current=connection.execute(select(Chapter.chapter_key).where(Chapter.id==target.chapter_id)).scalar_one_or_none()
    if current is None or (target.chapter_key is not None and target.chapter_key!=current):
        raise ValueError('The saved original belongs to a different chapter lifecycle')
    target.chapter_key=current
