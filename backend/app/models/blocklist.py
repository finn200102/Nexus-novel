from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint

from app.models.base import BaseModel

BLOCKLIST_KINDS = ("tag", "fandom", "genre", "author", "word")


class BlocklistEntry(BaseModel):
    """A per-user global hide rule applied to every discovery surface."""

    __tablename__ = "blocklist_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "value", name="uq_blocklist_user_kind_value"),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(20), nullable=False)
    value = Column(String(200), nullable=False)
