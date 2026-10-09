from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, UniqueConstraint, false
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
    # When shared, recipients see the owner's notes on the shelf's stories only if this is on.
    share_notes = Column(Boolean, nullable=False, default=False, server_default=false())

    entries = relationship("ShelfNovel", back_populates="shelf", cascade="all, delete-orphan")
    shares = relationship("ShelfShare", back_populates="shelf", cascade="all, delete-orphan")


class ShelfNovel(BaseModel):
    __tablename__ = "shelf_novels"
    __table_args__ = (
        UniqueConstraint("shelf_id", "novel_id", name="uq_shelf_novel"),
    )

    shelf_id = Column(Integer, ForeignKey("shelves.id", ondelete="CASCADE"), nullable=False, index=True)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False, index=True)
    position = Column(Integer, nullable=False, default=0, server_default="0")
    # Set when a collaborator (not the owner) put their own library copy on the shelf.
    added_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    shelf = relationship("Shelf", back_populates="entries")


SHARE_PERMISSIONS = ("view", "collaborate")


class ShelfShare(BaseModel):
    """A shelf shared with another user of the instance.

    Sharing grants catalog references only (title, author, source link, and
    the owner's notes when the owner opts in) — never the owner's downloaded
    chapter text, EPUBs or audio. A recipient adds the story to their own
    library and downloads it themselves.
    """

    __tablename__ = "shelf_shares"
    __table_args__ = (
        UniqueConstraint("shelf_id", "user_id", name="uq_shelf_share_user"),
    )

    shelf_id = Column(Integer, ForeignKey("shelves.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    permission = Column(String(16), nullable=False, default="view", server_default="view")

    shelf = relationship("Shelf", back_populates="shares")
