from sqlalchemy import JSON, Boolean, Column, ForeignKey, Integer, String, Text, UniqueConstraint, false

from app.models.base import BaseModel


class NovelPersonalData(BaseModel):
    """A user's private notes and personal rating (1-5) for one of their novels."""

    __tablename__ = "novel_personal_data"
    __table_args__ = (
        UniqueConstraint("user_id", "novel_id", name="uq_novel_personal_user_novel"),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    notes = Column(Text, nullable=True)
    rating = Column(Integer, nullable=True)
    # Chapter categories the user follows for this novel; NULL means ["story"].
    followed_categories = Column(JSON, nullable=True)
    # Queue downloads for the next ``keep_ahead`` undownloaded followed chapters
    # after the user's position whenever new chapters arrive.
    auto_download = Column(Boolean, nullable=False, default=False, server_default=false())
    keep_ahead = Column(Integer, nullable=False, default=10, server_default="10")


class NovelUserTag(BaseModel):
    __tablename__ = "novel_user_tags"
    __table_args__ = (
        UniqueConstraint("user_id", "novel_id", "tag", name="uq_novel_user_tag"),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False, index=True)
    tag = Column(String(60), nullable=False)
