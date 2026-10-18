"""Lease ownership and expiry for resumable download/audio workers."""
from alembic import op
import sqlalchemy as sa

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("chapter_download_jobs", "chapter_audio_jobs"):
        op.add_column(table, sa.Column("lease_owner", sa.String(255)))
        op.add_column(table, sa.Column("lease_expires_at", sa.DateTime()))
        op.create_index(f"ix_{table}_lease", table, ["status", "lease_expires_at"])


def downgrade():
    for table in ("chapter_download_jobs", "chapter_audio_jobs"):
        op.drop_index(f"ix_{table}_lease", table_name=table)
        op.drop_column(table, "lease_expires_at")
        op.drop_column(table, "lease_owner")
