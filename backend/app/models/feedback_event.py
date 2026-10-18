from sqlalchemy import Column, Float, ForeignKey, Index, Integer, String

from app.models.base import BaseModel


class ReaderFeedbackEvent(BaseModel):
    """One implicit or explicit signal a user gave about a novel.

    ``novel_id`` is deliberately not a foreign key: "removed" and "hidden" events
    must outlive the novel row they describe. Account deletion removes them.
    ``read_time`` is kept as a single upserted row per (user, novel).
    """

    __tablename__ = "reader_feedback_events"
    __table_args__ = (
        Index("ix_reader_feedback_user_novel", "user_id", "novel_id"),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    novel_id = Column(Integer, nullable=False)
    kind = Column(String(40), nullable=False)
    value = Column(Float, nullable=True)
