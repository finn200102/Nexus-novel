"""Immutable pronunciation snapshots for private narration."""
from alembic import op
import sqlalchemy as sa
revision = "0040"
down_revision = "0039"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chapter_audio_jobs", sa.Column("pronunciation_version", sa.String(64), nullable=True))
    op.add_column("chapter_audio_jobs", sa.Column("pronunciation_rules", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("chapter_audio_jobs", "pronunciation_rules")
    op.drop_column("chapter_audio_jobs", "pronunciation_version")
