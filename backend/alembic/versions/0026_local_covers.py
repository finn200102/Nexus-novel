"""Preserve raster EPUB covers privately and include them in database backups."""
from alembic import op
import sqlalchemy as sa

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("local_book_covers",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("created_at", sa.DateTime()), sa.Column("updated_at", sa.DateTime()),
        sa.Column("novel_id", sa.Integer(), sa.ForeignKey("novels.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("media_type", sa.String(32), nullable=False), sa.Column("data", sa.LargeBinary(), nullable=False),
    )
    op.create_index("ix_local_book_covers_id", "local_book_covers", ["id"])


def downgrade():
    op.drop_table("local_book_covers")
