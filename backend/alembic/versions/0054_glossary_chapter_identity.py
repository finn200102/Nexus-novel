"""Preserve numeric glossary entries for review, bind new scopes explicitly."""
from alembic import op
import sqlalchemy as sa
revision='0054'
down_revision='0053'
branch_labels=None
depends_on=None


def upgrade():
    with op.batch_alter_table('story_glossaries') as batch:
        batch.drop_constraint('uq_story_glossary_entry',type_='unique')
        batch.add_column(sa.Column('chapter_key',sa.String(36)))
        batch.add_column(sa.Column('manifest_epoch',sa.String(36)))
        batch.add_column(sa.Column('manifest_revision',sa.String(64)))
        batch.add_column(sa.Column('source_version',sa.String(64)))
        batch.add_column(sa.Column('prerequisites',sa.JSON()))
        batch.add_column(sa.Column('identity_inferred',sa.Boolean(),nullable=False,server_default=sa.true()))
    op.create_index('uq_story_glossary_legacy_scope','story_glossaries',['user_id','novel_id','source','language','through_chapter'],unique=True,
        sqlite_where=sa.text('identity_inferred = true'),postgresql_where=sa.text('identity_inferred = true'))
    op.create_index('uq_story_glossary_identity_scope','story_glossaries',['user_id','novel_id','source','language','chapter_key','manifest_epoch'],unique=True,
        sqlite_where=sa.text('identity_inferred = false'),postgresql_where=sa.text('identity_inferred = false'))


def downgrade():
    # Do not discard distinct reviewed lifecycle scopes to satisfy the older
    # numeric-only uniqueness rule; refuse a lossy downgrade explicitly.
    duplicate=op.get_bind().execute(sa.text('SELECT 1 FROM story_glossaries GROUP BY user_id,novel_id,source,language,through_chapter HAVING count(*)>1 LIMIT 1')).first()
    if duplicate:raise RuntimeError('Review duplicate glossary numeric scopes before downgrading; all terms were preserved.')
    op.drop_index('uq_story_glossary_identity_scope',table_name='story_glossaries')
    op.drop_index('uq_story_glossary_legacy_scope',table_name='story_glossaries')
    with op.batch_alter_table('story_glossaries') as batch:
        for name in ('identity_inferred','prerequisites','source_version','manifest_revision','manifest_epoch','chapter_key'):batch.drop_column(name)
        batch.create_unique_constraint('uq_story_glossary_entry',['user_id','novel_id','source','language','through_chapter'])
