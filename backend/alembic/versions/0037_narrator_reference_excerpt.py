"""Retain an explicitly selected reference excerpt through preparation retries."""
from alembic import op
import sqlalchemy as sa

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("voice_profiles", sa.Column("excerpt_start_seconds", sa.Float(), nullable=True))
    op.add_column("voice_profiles", sa.Column("excerpt_duration_seconds", sa.Float(), nullable=True))


def downgrade():
    with op.batch_alter_table("voice_profiles") as batch:
        batch.drop_column("excerpt_duration_seconds")
        batch.drop_column("excerpt_start_seconds")
