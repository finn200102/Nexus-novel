"""Explicit provider availability and declared translation languages."""
from alembic import op
import sqlalchemy as sa

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("reader_providers", sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("reader_providers", sa.Column("supported_languages", sa.JSON(), nullable=False, server_default="[]"))


def downgrade():
    op.drop_column("reader_providers", "supported_languages")
    op.drop_column("reader_providers", "enabled")
