"""Retain exact reading anchors; never guess quotes for existing positions."""
from alembic import op
import sqlalchemy as sa

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("reading_progress", "reading_annotations"):
        for name, limit in (("text_quote", 240), ("quote_prefix", 80), ("quote_suffix", 80),
                            ("locator_content_version", 64), ("locator_variant", 128)):
            op.add_column(table, sa.Column(name, sa.String(limit), nullable=True))


def downgrade():
    for table in ("reading_progress", "reading_annotations"):
        for name in ("text_quote", "quote_prefix", "quote_suffix", "locator_content_version", "locator_variant"):
            op.drop_column(table, name)
