"""Durable MP3 derivatives for explicitly activated private podcast feeds."""
from alembic import op
import sqlalchemy as sa

revision = "0041"
down_revision = "0040"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("podcast_audio_jobs",
        sa.Column("id",sa.Integer(),primary_key=True),
        sa.Column("created_at",sa.DateTime(),nullable=True),
        sa.Column("updated_at",sa.DateTime(),nullable=True),
        sa.Column("user_id",sa.Integer(),sa.ForeignKey("users.id",ondelete="CASCADE"),nullable=False),
        sa.Column("novel_id",sa.Integer(),sa.ForeignKey("novels.id",ondelete="CASCADE"),nullable=False),
        sa.Column("source_audio_job_id",sa.Integer(),sa.ForeignKey("chapter_audio_jobs.id",ondelete="CASCADE"),nullable=False),
        sa.Column("chapter_number",sa.Integer(),nullable=False),
        sa.Column("pipeline_version",sa.String(80),nullable=False),
        sa.Column("source_snapshot",sa.JSON(),nullable=False),
        sa.Column("status",sa.String(20),nullable=False,server_default="queued"),
        sa.Column("audio_path",sa.String(1000),nullable=True),
        sa.Column("audio_bytes",sa.BigInteger(),nullable=True),
        sa.Column("duration_seconds",sa.Float(),nullable=True),
        sa.Column("lease_owner",sa.String(255),nullable=True),
        sa.Column("lease_expires_at",sa.DateTime(),nullable=True),
        sa.Column("attempt_count",sa.Integer(),nullable=False,server_default="0"),
        sa.Column("max_attempts",sa.Integer(),nullable=False,server_default="3"),
        sa.Column("next_attempt_at",sa.DateTime(),nullable=True),
        sa.Column("started_at",sa.DateTime(),nullable=True),
        sa.Column("finished_at",sa.DateTime(),nullable=True),
        sa.Column("error_code",sa.String(80),nullable=True),
        sa.Column("error",sa.Text(),nullable=True),
        sa.UniqueConstraint("user_id","source_audio_job_id","pipeline_version",name="uq_podcast_audio_source"))
    op.create_index("ix_podcast_audio_jobs_id","podcast_audio_jobs",["id"])
    op.create_index("ix_podcast_audio_queue","podcast_audio_jobs",["status","next_attempt_at","created_at"])
    op.create_index("ix_podcast_audio_lease","podcast_audio_jobs",["status","lease_expires_at"])


def downgrade():
    op.drop_table("podcast_audio_jobs")
