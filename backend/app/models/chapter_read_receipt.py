from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, UniqueConstraint, false, event, select
from app.models.base import BaseModel


class ChapterReadReceipt(BaseModel):
    __tablename__ = "chapter_read_receipts"
    __table_args__ = (UniqueConstraint("user_id", "chapter_key", "content_version", name="uq_chapter_read_identity_version"),)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    chapter_key = Column(String(36), nullable=True)
    content_version = Column(String(64), nullable=False)
    completed = Column(Boolean, nullable=False, default=False, server_default=false())
    requires_review = Column(Boolean, nullable=False, default=False, server_default=false())


@event.listens_for(ChapterReadReceipt, 'before_insert')
def bind_receipt_identity(mapper, connection, target):
    # New genuine receipts bind the referenced lifecycle, not a reusable PK.
    from app.models.chapter import Chapter
    current=connection.execute(select(Chapter.chapter_key).where(Chapter.id==target.chapter_id,Chapter.archived.is_(False))).scalar_one_or_none()
    if current is None:
        raise ValueError('A read receipt requires an active, identified chapter')
    if target.chapter_key is not None and target.chapter_key!=current:
        raise ValueError('The read receipt belongs to a different chapter lifecycle')
    target.chapter_key=current
