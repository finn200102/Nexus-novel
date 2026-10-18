"""Preserve unknown device positions without guessing their exported chapter identities."""
from alembic import op
import sqlalchemy as sa
revision='0056'
down_revision='0055'
branch_labels=None
depends_on=None


def upgrade():
    for name,type_ in [('source_snapshot',sa.JSON()),('spine_identity',sa.JSON()),('owner_storage_id',sa.String(36)),('manifest_epoch',sa.String(36)),('reading_run_key',sa.String(36))]:
        op.add_column('epub_builds',sa.Column(name,type_,nullable=True))
    op.add_column('kosync_progress',sa.Column('progress_review_reason',sa.String(80),nullable=True))
    for name,size in [('bookmark_fingerprint',64),('confirmed_fingerprint',64),('confirmed_reading_run_key',36),('progress_review_reason',80)]:
        op.add_column('kobo_synced_books',sa.Column(name,sa.String(size),nullable=True))
    op.execute("UPDATE kosync_progress SET progress_review_reason='book_identity_unknown'")
    op.execute("UPDATE kobo_synced_books SET progress_review_reason='book_version_confirmation_required'")


def downgrade():
    for name in ('progress_review_reason','confirmed_reading_run_key','confirmed_fingerprint','bookmark_fingerprint'):op.drop_column('kobo_synced_books',name)
    op.drop_column('kosync_progress','progress_review_reason')
    for name in ('reading_run_key','manifest_epoch','owner_storage_id','spine_identity','source_snapshot'):op.drop_column('epub_builds',name)
