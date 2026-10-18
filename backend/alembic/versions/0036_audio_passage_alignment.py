"""Bind new narration to retained originals and measured passage boundaries."""
from alembic import op
import sqlalchemy as sa
revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chapter_audio_jobs", sa.Column("source_version", sa.String(64), nullable=True))
    op.add_column("chapter_audio_jobs", sa.Column("include_author_notes", sa.Boolean(), nullable=True))
    op.add_column("chapter_audio_parts", sa.Column("block_id", sa.String(100), nullable=True))
    op.add_column("chapter_audio_parts", sa.Column("text_offset", sa.Integer(), nullable=True))
    op.add_column("chapter_audio_parts", sa.Column("text_length", sa.Integer(), nullable=True))
    op.add_column("chapter_audio_parts", sa.Column("duration_seconds", sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table("chapter_audio_parts") as batch:
        for name in ("duration_seconds", "text_length", "text_offset", "block_id"):
            batch.drop_column(name)
    with op.batch_alter_table("chapter_audio_jobs") as batch:
        batch.drop_column("include_author_notes")
        batch.drop_column("source_version")
