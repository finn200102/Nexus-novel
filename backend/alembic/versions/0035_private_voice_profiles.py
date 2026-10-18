"""Account-owned local narrator references and resumable preparation."""
from alembic import op
import sqlalchemy as sa
revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("voice_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime()), sa.Column("updated_at", sa.DateTime()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False), sa.Column("language", sa.String(32), nullable=False),
        sa.Column("sample", sa.LargeBinary(), nullable=False), sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("preview", sa.LargeBinary()), sa.Column("model", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("lease_owner", sa.String(255)), sa.Column("lease_expires_at", sa.DateTime()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_attempt_at", sa.DateTime()), sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()), sa.Column("error_code", sa.String(80)), sa.Column("error", sa.Text()))
    op.create_index("ix_voice_profiles_id", "voice_profiles", ["id"])
    op.create_index("ix_voice_profiles_user_id", "voice_profiles", ["user_id"])
    with op.batch_alter_table("chapter_audio_jobs") as batch:
        batch.add_column(sa.Column("voice_profile_id", sa.Integer(), nullable=True))
        batch.create_foreign_key("fk_audio_voice_profile", "voice_profiles", ["voice_profile_id"], ["id"], ondelete="SET NULL")


def downgrade():
    with op.batch_alter_table("chapter_audio_jobs") as batch:
        batch.drop_constraint("fk_audio_voice_profile", type_="foreignkey")
        batch.drop_column("voice_profile_id")
    op.drop_table("voice_profiles")
