from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from app.models.base import BaseModel
from uuid import uuid4


class SavedSearch(BaseModel):
    __tablename__ = "saved_searches"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_saved_search_user_name"),
        Index('uq_saved_searches_identity_key', 'identity_key', unique=True))
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    identity_key = Column(String(36), nullable=True, default=lambda: str(uuid4()))
    filters = Column(JSON, nullable=False, default=dict)
    notify_on_match = Column(Boolean, nullable=False, default=False)
