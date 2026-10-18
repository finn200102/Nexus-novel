"""Record completed content versions; retain all legacy history unchanged."""
from alembic import op
import sqlalchemy as sa

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("chapter_read_receipts",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("created_at", sa.DateTime()), sa.Column("updated_at", sa.DateTime()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chapter_id", sa.Integer(), sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_version", sa.String(64), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("requires_review", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("user_id", "chapter_id", "content_version", name="uq_chapter_read_version"))
    op.create_index("ix_chapter_read_receipts_id", "chapter_read_receipts", ["id"])


def downgrade():
    op.drop_table("chapter_read_receipts")
