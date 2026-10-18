"""Private providers, bounded glossaries and resumable translation variants."""
from alembic import op
import sqlalchemy as sa

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def common():
    return [sa.Column("id", sa.Integer(), primary_key=True), sa.Column("created_at", sa.DateTime()), sa.Column("updated_at", sa.DateTime())]


def upgrade():
    op.create_table("reader_providers", *common(),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("base_url", sa.String(1000), nullable=False), sa.Column("model", sa.String(255), nullable=False),
        sa.Column("secret_ciphertext", sa.Text()),
        sa.Column("input_price", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("output_price", sa.Numeric(12, 6), nullable=False, server_default="0"),
        *[sa.Column(name, sa.BigInteger(), nullable=False, server_default="0") for name in ("budget_microusd", "used_microusd", "reserved_microusd")],
    )
    op.create_table("story_glossaries", *common(),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("novel_id", sa.Integer(), sa.ForeignKey("novels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source", sa.String(120), nullable=False), sa.Column("target", sa.String(300), nullable=False),
        sa.Column("language", sa.String(20), nullable=False), sa.Column("through_chapter", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_id", "novel_id", "source", "language", "through_chapter", name="uq_story_glossary_entry"),
    )
    op.create_table("translation_jobs", *common(),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("novel_id", sa.Integer(), sa.ForeignKey("novels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chapter_id", sa.Integer(), sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("reader_providers.id"), nullable=False),
        sa.Column("language", sa.String(20), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("source_version", sa.String(64), nullable=False),
        *[sa.Column(name, sa.JSON(), nullable=False) for name in ("provider_snapshot", "source_blocks", "glossary", "translated_blocks")],
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        *[sa.Column(name, sa.DateTime()) for name in ("next_attempt_at", "started_at", "finished_at", "lease_expires_at")],
        sa.Column("lease_owner", sa.String(255)), sa.Column("error", sa.Text()), sa.Column("error_code", sa.String(80)),
        *[sa.Column(name, sa.BigInteger(), nullable=False, server_default="0") for name in ("input_tokens", "output_tokens", "charged_microusd")],
        sa.UniqueConstraint("user_id", "chapter_id", "fingerprint", name="uq_translation_variant"),
    )
    for table in ("reader_providers", "story_glossaries", "translation_jobs"):
        op.create_index(f"ix_{table}_id", table, ["id"])


def downgrade():
    for table in ("translation_jobs", "story_glossaries", "reader_providers"):
        op.drop_table(table)
