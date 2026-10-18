from sqlalchemy import Column, ForeignKey, Integer, JSON, String, UniqueConstraint
from app.models.base import BaseModel


class CompanionAnswer(BaseModel):
    __tablename__ = "companion_answers"
    __table_args__ = (UniqueConstraint("user_id", "novel_id", "fingerprint", name="uq_private_companion_answer"),)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    response = Column(JSON, nullable=False)
