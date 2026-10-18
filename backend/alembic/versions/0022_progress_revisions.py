"""Protect reading state against stale-device saves and retain read-through state."""
from alembic import op
import sqlalchemy as sa

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade():
    for name, typ, default in (
        ("revision", sa.Integer(), "0"), ("furthest_chapter_number", sa.Integer(), "0"),
        ("furthest_percent", sa.Float(), "0"), ("text_offset", sa.Integer(), "0"),
    ):
        op.add_column("reading_progress", sa.Column(name, typ, nullable=False, server_default=default))
    for name in ("block_id", "device_id"):
        op.add_column("reading_progress", sa.Column(name, sa.String(128)))
    op.execute("UPDATE reading_progress SET furthest_chapter_number = COALESCE(chapter_number, 0), furthest_percent = percent")
    op.create_table("reading_progress_operations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime()), sa.Column("updated_at", sa.DateTime()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("novel_id", sa.Integer(), sa.ForeignKey("novels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False), sa.Column("response", sa.JSON(), nullable=False),
        sa.UniqueConstraint("user_id", "operation_id", name="uq_progress_user_operation"),
    )
    op.create_index("ix_reading_progress_operations_id", "reading_progress_operations", ["id"])


def downgrade():
    op.drop_table("reading_progress_operations")
    for name in ("revision", "furthest_chapter_number", "furthest_percent", "block_id", "text_offset", "device_id"):
        op.drop_column("reading_progress", name)
