from uuid import uuid4
from sqlalchemy import String, FetchedValue, Index
from app.models.export_lifecycle import register
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, Text, event, select
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class ReadingAnnotation(BaseModel):
    __tablename__ = "reading_annotations"
    __table_args__ = (Index("uq_reading_annotations_export_key", "export_key", unique=True),)

    export_key = Column(String(36), nullable=True, default=lambda: str(uuid4()), server_default=FetchedValue())

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    chapter_key = Column(String(36), nullable=True)
    chapter_number = Column(Integer, nullable=True)
    annotation_type = Column(String(20), nullable=False, default="bookmark", server_default="bookmark")
    position = Column(Integer, nullable=False, default=0, server_default="0")
    percent = Column(Float, nullable=False, default=0, server_default="0")
    quote = Column(Text, nullable=True)
    note = Column(Text, nullable=True)
    block_id = Column(String(128), nullable=True)
    text_offset = Column(Integer, nullable=False, default=0, server_default="0")
    text_quote = Column(String(240), nullable=True)
    quote_prefix = Column(String(80), nullable=True)
    quote_suffix = Column(String(80), nullable=True)
    locator_content_version = Column(String(64), nullable=True)
    locator_variant = Column(String(128), nullable=True)
    # Set once the annotation has been pushed to Readwise; keeps syncs idempotent.
    exported_at = Column(DateTime, nullable=True)

    user = relationship("User")
    novel = relationship("Novel")
    chapter = relationship("Chapter")


@event.listens_for(ReadingAnnotation,'before_insert')
def bind_annotation_identity(mapper,connection,target):
    from app.models.chapter import Chapter
    current=connection.execute(select(Chapter.chapter_key,Chapter.chapter_number).where(Chapter.id==target.chapter_id)).first()
    if current is None or current.chapter_key is None or (target.chapter_key is not None and target.chapter_key!=current.chapter_key):
        raise ValueError('The annotation belongs to a different chapter lifecycle')
    target.chapter_key=current.chapter_key
    if target.chapter_number is None:target.chapter_number=current.chapter_number


register(ReadingAnnotation.__table__)
