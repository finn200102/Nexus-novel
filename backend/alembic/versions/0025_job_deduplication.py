"""Allow one active job per reader/chapter and retain prior completed artifacts."""
from alembic import op
import sqlalchemy as sa

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None
ACTIVE = "status IN ('queued', 'processing', 'retry_wait')"


def upgrade():
    for table, index in (("chapter_download_jobs", "uq_active_chapter_download"), ("chapter_audio_jobs", "uq_active_chapter_audio")):
        # Prefer a currently running job; keep all other rows as cancelled
        # history rather than deleting their partial files or reports.
        op.execute(f"""UPDATE {table} SET status = 'cancelled', lease_owner = NULL, lease_expires_at = NULL
            WHERE id IN (SELECT id FROM (SELECT id, ROW_NUMBER() OVER (
                PARTITION BY user_id, chapter_id ORDER BY CASE WHEN status = 'processing' THEN 0 ELSE 1 END, id
            ) AS rn FROM {table} WHERE {ACTIVE}) AS duplicate_jobs WHERE rn > 1)""")
        op.create_index(index, table, ["user_id", "chapter_id"], unique=True,
                        sqlite_where=sa.text(ACTIVE), postgresql_where=sa.text(ACTIVE))


def downgrade():
    for table, index in (("chapter_download_jobs", "uq_active_chapter_download"), ("chapter_audio_jobs", "uq_active_chapter_audio")):
        op.drop_index(index, table_name=table)
