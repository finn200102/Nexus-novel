from sqlalchemy import BigInteger, Boolean, Column, ForeignKey, Integer, JSON, String, Text, DateTime, UniqueConstraint, Numeric, true, Index
from sqlalchemy import false
from sqlalchemy import text as sql_text
from app.models.base import BaseModel


class ReaderProvider(BaseModel):
    __tablename__ = "reader_providers"
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(120), nullable=False)
    kind = Column(String(32), nullable=False)
    base_url = Column(String(1000), nullable=False)
    model = Column(String(255), nullable=False)
    secret_ciphertext = Column(Text, nullable=True)
    enabled = Column(Boolean, nullable=False, default=True, server_default=true())
    capabilities = Column(JSON, nullable=True)
    image_model = Column(String(255), nullable=True)
    image_price_microusd = Column(BigInteger, nullable=False, default=0, server_default="0")
    image_sizes = Column(JSON, nullable=False, default=list, server_default="[]")
    image_qualities = Column(JSON, nullable=False, default=list, server_default="[]")
    supported_languages = Column(JSON, nullable=False, default=list, server_default="[]")
    input_price = Column(Numeric(12, 6), nullable=False, default=0, server_default="0")
    output_price = Column(Numeric(12, 6), nullable=False, default=0, server_default="0")
    budget_microusd = Column(BigInteger, nullable=False, default=0, server_default="0")
    used_microusd = Column(BigInteger, nullable=False, default=0, server_default="0")
    reserved_microusd = Column(BigInteger, nullable=False, default=0, server_default="0")


class StoryGlossary(BaseModel):
    __tablename__ = "story_glossaries"
    __table_args__ = (
        Index('uq_story_glossary_legacy_scope','user_id','novel_id','source','language','through_chapter',unique=True,
              sqlite_where=sql_text('identity_inferred = true'),postgresql_where=sql_text('identity_inferred = true')),
        Index('uq_story_glossary_identity_scope','user_id','novel_id','source','language','chapter_key','manifest_epoch',unique=True,
              sqlite_where=sql_text('identity_inferred = false'),postgresql_where=sql_text('identity_inferred = false')),
    )
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    source = Column(String(120), nullable=False)
    target = Column(String(300), nullable=False)
    language = Column(String(20), nullable=False)
    through_chapter = Column(Integer, nullable=False)
    chapter_key = Column(String(36), nullable=True)
    manifest_epoch = Column(String(36), nullable=True)
    manifest_revision = Column(String(64), nullable=True)
    source_version = Column(String(64), nullable=True)
    prerequisites = Column(JSON, nullable=True)
    identity_inferred = Column(Boolean, nullable=False, default=True, server_default=true())


class TranslationJob(BaseModel):
    __tablename__ = "translation_jobs"
    __table_args__ = (UniqueConstraint("user_id", "chapter_id", "fingerprint", name="uq_translation_variant"),)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    novel_id = Column(Integer, ForeignKey("novels.id", ondelete="CASCADE"), nullable=False)
    chapter_id = Column(Integer, ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False)
    provider_id = Column(Integer, ForeignKey("reader_providers.id"), nullable=False)
    language = Column(String(20), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    source_version = Column(String(64), nullable=False)
    chapter_key = Column(String(36), nullable=True)
    manifest_epoch = Column(String(36), nullable=True)
    manifest_revision = Column(String(64), nullable=True)
    chapter_title_snapshot = Column(Text, nullable=True)
    chapter_number_snapshot = Column(Integer, nullable=True)
    identity_inferred = Column(Boolean, nullable=False, default=False, server_default=false())
    provider_snapshot = Column(JSON, nullable=False)
    source_blocks = Column(JSON, nullable=False)
    glossary = Column(JSON, nullable=False)
    translated_blocks = Column(JSON, nullable=False, default=list)
    status = Column(String(20), nullable=False, default="queued", server_default="queued")
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    max_attempts = Column(Integer, nullable=False, default=3, server_default="3")
    paid_retry_generation = Column(Integer, nullable=False, default=0, server_default="0")
    next_attempt_at = Column(DateTime)
    started_at = Column(DateTime)
    finished_at = Column(DateTime)
    lease_owner = Column(String(255))
    lease_expires_at = Column(DateTime)
    error = Column(Text)
    error_code = Column(String(80))
    input_tokens = Column(BigInteger, nullable=False, default=0, server_default="0")
    output_tokens = Column(BigInteger, nullable=False, default=0, server_default="0")
    charged_microusd = Column(BigInteger, nullable=False, default=0, server_default="0")


class ReaderProviderRequest(BaseModel):
    """Private accounting metadata only; never prompts, secrets or responses."""
    __tablename__ = "reader_provider_requests"
    __table_args__ = (UniqueConstraint("translation_job_id", "translation_block_index", "retry_generation", name="uq_paid_translation_dispatch"), Index("uq_provider_work_dispatch", "user_id", "purpose", "job_key", "item_key", "retry_generation", unique=True))
    request_key = Column(String(36), nullable=False, unique=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider_id = Column(Integer, ForeignKey("reader_providers.id", ondelete="CASCADE"), nullable=False, index=True)
    model_snapshot = Column(JSON, nullable=False)
    status = Column(String(24), nullable=False)
    revision = Column(Integer, nullable=False, default=0, server_default="0")
    reserved_microusd = Column(BigInteger, nullable=False)
    actual_microusd = Column(BigInteger)
    input_tokens = Column(BigInteger)
    output_tokens = Column(BigInteger)
    expires_at = Column(DateTime)
    resolved_at = Column(DateTime)
    # Historical identifiers intentionally have no cascading source FK: accounting
    # must survive removal of a translation variant or its story.
    purpose = Column(String(32), nullable=True)
    job_key = Column(String(64), nullable=True)
    item_key = Column(String(120), nullable=True)
    translation_job_id = Column(Integer)
    translation_block_index = Column(Integer)
    retry_generation = Column(Integer)


class ReaderProviderReconciliationOperation(BaseModel):
    __tablename__ = "reader_provider_reconciliation_operations"
    __table_args__ = (UniqueConstraint("user_id", "operation_id", name="uq_provider_reconciliation_operation"),)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider_id = Column(Integer, ForeignKey("reader_providers.id", ondelete="CASCADE"), nullable=False)
    operation_id = Column(String(128), nullable=False)
    fingerprint = Column(String(64), nullable=False)
    response = Column(JSON, nullable=False)
