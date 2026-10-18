"""Retain private source versions without inventing earlier chapter contents."""
from alembic import op
import sqlalchemy as sa

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("chapter_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime()), sa.Column("updated_at", sa.DateTime()),
        sa.Column("chapter_id", sa.Integer(), sa.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content_version", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255)), sa.Column("source_url", sa.String(500)),
        sa.Column("content", sa.Text(), nullable=False), sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False), sa.Column("reason", sa.String(32), nullable=False),
        sa.UniqueConstraint("chapter_id", "content_version", name="uq_chapter_version"))
    op.create_index("ix_chapter_versions_id", "chapter_versions", ["id"])


def downgrade():
    op.drop_table("chapter_versions")
