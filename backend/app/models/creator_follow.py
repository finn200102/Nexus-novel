from sqlalchemy import Column, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import relationship

from app.models.base import BaseModel


class CreatorFollow(BaseModel):
    """A reader following an author page or a series on one source site.

    ``target_key`` is the source's own key (numeric user id, AO3 user name or
    "pseud (user)", AO3 series id); the metadata server refreshes the target
    while anyone follows it and reports new works back as webhook events.
    """

    __tablename__ = "creator_follows"
    __table_args__ = (
        UniqueConstraint("user_id", "kind", "site", "target_key", name="uq_creator_follow"),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(16), nullable=False)  # author | series
    site = Column(String(64), nullable=False)
    target_key = Column(String(255), nullable=False)
    name = Column(String(255), nullable=True)
    metadata_author_id = Column(Integer, nullable=True)
    metadata_target_id = Column(Integer, nullable=True, index=True)

    user = relationship("User")
