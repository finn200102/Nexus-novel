from sqlalchemy import Column, ForeignKey, Integer, JSON, String, UniqueConstraint
from app.models.base import BaseModel


class ReaderPreference(BaseModel):
    __tablename__ = "reader_preferences"
    __table_args__ = (UniqueConstraint("user_id", "scope", name="uq_reader_preferences_scope"),)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=True)
    scope = Column(String(40), nullable=False)
    revision = Column(Integer, nullable=False, default=0, server_default="0")
    values = Column(JSON, nullable=False, default=dict)


class ReaderPreferenceOperation(BaseModel):
    __tablename__ = "reader_preference_operations"
    __table_args__ = (UniqueConstraint("user_id", "operation_id", name="uq_reader_preference_operation"),)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    operation_id = Column(String(128), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    response = Column(JSON, nullable=False)
