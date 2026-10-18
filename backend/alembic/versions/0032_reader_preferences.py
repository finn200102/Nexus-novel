"""Add private revisioned reader preferences without changing local/server progress."""
from alembic import op
import sqlalchemy as sa

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("reader_preferences",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("created_at", sa.DateTime()), sa.Column("updated_at", sa.DateTime()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("novel_id", sa.Integer(), sa.ForeignKey("novels.id", ondelete="CASCADE")),
        sa.Column("scope", sa.String(40), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.UniqueConstraint("user_id", "scope", name="uq_reader_preferences_scope"))
    op.create_index("ix_reader_preferences_id", "reader_preferences", ["id"])
    op.create_table("reader_preference_operations",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("created_at", sa.DateTime()), sa.Column("updated_at", sa.DateTime()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("operation_id", sa.String(128), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False), sa.Column("response", sa.JSON(), nullable=False),
        sa.UniqueConstraint("user_id", "operation_id", name="uq_reader_preference_operation"))
    op.create_index("ix_reader_preference_operations_id", "reader_preference_operations", ["id"])


def downgrade():
    op.drop_table("reader_preference_operations")
    op.drop_table("reader_preferences")
