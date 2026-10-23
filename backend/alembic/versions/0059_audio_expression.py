"""Persist opt-in narration expression settings and resumable spoken copies."""
from alembic import op
import sqlalchemy as sa
revision = '0059'
down_revision = '0058'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('chapter_audio_jobs', sa.Column('preparation', sa.JSON(), nullable=True))
    op.add_column('chapter_audio_jobs', sa.Column('preparation_version', sa.String(64), nullable=True))
    op.add_column('chapter_audio_parts', sa.Column('synthesis_text', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('chapter_audio_parts') as batch:
        batch.drop_column('synthesis_text')
    with op.batch_alter_table('chapter_audio_jobs') as batch:
        batch.drop_column('preparation_version')
        batch.drop_column('preparation')
