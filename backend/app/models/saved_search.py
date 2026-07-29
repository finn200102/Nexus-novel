from sqlalchemy import Boolean, Column, ForeignKey, Integer, JSON, String, UniqueConstraint
from app.models.base import BaseModel


class SavedSearch(BaseModel):
    __tablename__ = "saved_searches"
    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_saved_search_user_name"),)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    filters = Column(JSON, nullable=False, default=dict)
    notify_on_match = Column(Boolean, nullable=False, default=False)
