"""Private explicit external-processing choices per story and provider."""
from alembic import op
import sqlalchemy as sa

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("story_processing_permissions",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("created_at", sa.DateTime()), sa.Column("updated_at", sa.DateTime()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("novel_id", sa.Integer(), sa.ForeignKey("novels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider_id", sa.Integer(), sa.ForeignKey("reader_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("translation", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("companion", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ao3_consent", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("user_id", "novel_id", "provider_id", name="uq_story_processing_permission"))
    op.create_index("ix_story_processing_permissions_id", "story_processing_permissions", ["id"])


def downgrade():
    op.drop_table("story_processing_permissions")
