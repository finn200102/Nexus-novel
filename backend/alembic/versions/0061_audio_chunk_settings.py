"""Persist local Qwen narration input and output budgets."""
from alembic import op
import sqlalchemy as sa

revision = '0061'
down_revision = '0060'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chapter_audio_jobs', sa.Column('qwen_chunk_size', sa.Integer(), nullable=True))
    op.add_column('chapter_audio_jobs', sa.Column('generation_token_limit', sa.Integer(), nullable=True))
    op.add_column('chapter_audio_parts', sa.Column('source_spans', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('chapter_audio_parts', 'source_spans')
    op.drop_column('chapter_audio_jobs', 'generation_token_limit')
    op.drop_column('chapter_audio_jobs', 'qwen_chunk_size')
