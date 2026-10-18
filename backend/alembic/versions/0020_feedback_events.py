"""Persist the private reader feedback model introduced during catalog work."""
from alembic import op
import sqlalchemy as sa

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "reader_feedback_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime()),
        sa.Column("updated_at", sa.DateTime()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("novel_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("value", sa.Float()),
    )
    op.create_index("ix_reader_feedback_events_id", "reader_feedback_events", ["id"])
    op.create_index("ix_reader_feedback_events_user_id", "reader_feedback_events", ["user_id"])
    op.create_index("ix_reader_feedback_user_novel", "reader_feedback_events", ["user_id", "novel_id"])


def downgrade():
    op.drop_table("reader_feedback_events")
