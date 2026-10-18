"""Cache cited answers privately by content, boundary, provider and pipeline."""
from alembic import op
import sqlalchemy as sa

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("companion_answers",
        sa.Column("id", sa.Integer(), primary_key=True), sa.Column("created_at", sa.DateTime()), sa.Column("updated_at", sa.DateTime()),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("novel_id", sa.Integer(), sa.ForeignKey("novels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False), sa.Column("response", sa.JSON(), nullable=False),
        sa.UniqueConstraint("user_id", "novel_id", "fingerprint", name="uq_private_companion_answer"))
    op.create_index("ix_companion_answers_id", "companion_answers", ["id"])


def downgrade():
    op.drop_table("companion_answers")
