"""Add rich chapter blocks and stable annotation locators; retain original text."""
from alembic import op
import sqlalchemy as sa

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("chapters", sa.Column("document", sa.JSON()))
    op.add_column("reading_annotations", sa.Column("block_id", sa.String(128)))
    op.add_column("reading_annotations", sa.Column("text_offset", sa.Integer(), nullable=False, server_default="0"))


def downgrade():
    op.drop_column("chapters", "document")
    op.drop_column("reading_annotations", "block_id")
    op.drop_column("reading_annotations", "text_offset")
