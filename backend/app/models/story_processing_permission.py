from sqlalchemy import Boolean, Column, ForeignKey, Integer, UniqueConstraint, false, JSON
from app.models.base import BaseModel


class StoryProcessingPermission(BaseModel):
    __tablename__ = "story_processing_permissions"
    __table_args__ = (UniqueConstraint("user_id", "novel_id", "provider_id", name="uq_story_processing_permission"),)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    provider_id = Column(Integer, ForeignKey("reader_providers.id", ondelete="CASCADE"), nullable=False)
    translation = Column(Boolean().evaluates_none(), nullable=True, default=False, server_default=false())
    # A translation-only grant leaves companion permission undecided. Existing
    # explicit denials keep False and cannot be bypassed by request consent.
    companion = Column(Boolean().evaluates_none(), nullable=True, default=False, server_default=false())
    ao3_consent = Column(Boolean, nullable=False, default=False, server_default=false())

    portrait = Column(Boolean, nullable=False, default=False, server_default=false())
    portrait_ao3_consent = Column(Boolean, nullable=False, default=False, server_default=false())
    portrait_provider_snapshot = Column(JSON, nullable=True)
