"""Bind derivative jobs to immutable chapter lifecycles without inventing originals."""
from alembic import op
import sqlalchemy as sa

revision = '0053'
down_revision = '0052'
branch_labels = None
depends_on = None


def upgrade():
    add_identity('chapter_audio_jobs', audio=True)
    add_identity('translation_jobs')
    # A numeric FK cannot establish the original queue-time chapter lifecycle.
    # Existing jobs remain unbound for explicit review; never backfill authority.
    op.add_column('chapter_download_jobs', sa.Column('chapter_identity', sa.JSON(), nullable=True))


def add_identity(table, *, audio=False):
    for column in [sa.Column('chapter_key', sa.String(36)),
                   sa.Column('manifest_epoch', sa.String(36)),
                   sa.Column('manifest_revision', sa.String(64)),
                   sa.Column('chapter_title_snapshot', sa.Text()),
                   sa.Column('chapter_number_snapshot', sa.Integer()),
                   sa.Column('identity_inferred', sa.Boolean(), nullable=False, server_default=sa.false())]:
        op.add_column(table, column)
    # Existing FKs establish the current owned row, not the original queue-time
    # title, number or manifest revision. Mark this migration binding inferred;
    # preserve source_version and leave unavailable original display fields NULL.
    connection = op.get_bind()
    connection.execute(sa.text(f'UPDATE {table} SET identity_inferred = true'))
    proof = f"""FROM chapters c
        JOIN novels n ON n.id = c.novel_id
        JOIN libraries l ON l.id = n.library_id
        JOIN chapter_manifest_states s ON s.novel_id = n.id
        WHERE c.id = {table}.chapter_id
          AND c.novel_id = {table}.novel_id
          AND l.user_id = {table}.user_id
          AND c.chapter_key IS NOT NULL"""
    if audio:
        proof += f' AND n.library_id = {table}.library_id'
    connection.execute(sa.text(f"""UPDATE {table} SET
        chapter_key = (SELECT c.chapter_key {proof}),
        manifest_epoch = (SELECT s.manifest_epoch {proof}),
        manifest_revision = (SELECT CAST(s.revision AS VARCHAR(64)) {proof})
        WHERE EXISTS (SELECT 1 {proof})"""))


def downgrade():
    op.drop_column('chapter_download_jobs', 'chapter_identity')
    for table in ('translation_jobs', 'chapter_audio_jobs'):
        for name in ('identity_inferred', 'chapter_number_snapshot', 'chapter_title_snapshot',
                     'manifest_revision', 'manifest_epoch', 'chapter_key'):
            op.drop_column(table, name)
