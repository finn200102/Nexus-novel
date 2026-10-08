from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class Shelf(BaseModel):
    """A user-named collection. Shelves span libraries; a novel may sit on many."""

    __tablename__ = "shelves"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_shelves_user_name"),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(120), nullable=False)
    position = Column(Integer, nullable=False, default=0, server_default="0")

    entries = relationship("ShelfNovel", back_populates="shelf", cascade="all, delete-orphan")


class ShelfNovel(BaseModel):
    __tablename__ = "shelf_novels"
    __table_args__ = (
        UniqueConstraint("shelf_id", "novel_id", name="uq_shelf_novel"),
    )

    shelf_id = Column(Integer, ForeignKey("shelves.id", ondelete="CASCADE"), nullable=False, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False, default=0, server_default="0")

    shelf = relationship("Shelf", back_populates="entries")
