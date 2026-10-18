"""Stable local chapter identity, preserved archives and reviewed topology."""
from uuid import uuid4
from alembic import op
import sqlalchemy as sa

revision = '0052'
down_revision = '0051'
branch_labels = None
depends_on = None


def _timestamps():
    return [sa.Column('id',sa.Integer(),primary_key=True),sa.Column('created_at',sa.DateTime()),sa.Column('updated_at',sa.DateTime())]


def upgrade():
    connection=op.get_bind()
    # Some already-stamped pre-Alembic databases also lack nullable base facts.
    # Repair their shape before provenance queries; missing facts stay unknown.
    novel_columns={value['name'] for value in sa.inspect(connection).get_columns('novels')}
    for name,kind in [('author_id',sa.Integer()),('site_story_id',sa.BigInteger()),('site',sa.String(255)),
        ('description',sa.Text()),('cover_image',sa.String(255)),('file_path',sa.String(255)),
        ('num_chapters',sa.Integer()),('genre_id',sa.Integer())]:
        if name not in novel_columns:op.add_column('novels',sa.Column(name,kind,nullable=True))
    for column in [sa.Column('chapter_key',sa.String(36)),sa.Column('metadata_manifest_key',sa.String(36)),
        sa.Column('metadata_chapter_key',sa.String(36)),sa.Column('archived',sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column('archived_at',sa.DateTime())]:
        op.add_column('chapters',column)
    # Pre-Alembic installations may have SQLite's unnamed UNIQUE constraint;
    # discover the ordinal key by columns rather than assuming its modern name.
    ordinal_constraints=[value for value in sa.inspect(connection).get_unique_constraints('chapters')
        if set(value['column_names'])=={'novel_id','chapter_number'}]
    with op.batch_alter_table('chapters',naming_convention={'uq':'uq_legacy_%(table_name)s_%(column_0_name)s'}) as batch:
        for constraint in ordinal_constraints:
            batch.drop_constraint(constraint['name'] or 'uq_legacy_chapters_novel_id',type_='unique')
        batch.create_unique_constraint('uq_chapter_lifecycle_key',['chapter_key'])
    op.create_index('uq_active_chapter_novel_number','chapters',['novel_id','chapter_number'],unique=True,
        sqlite_where=sa.text('archived = 0'),postgresql_where=sa.text('archived = false'))
    op.create_table('chapter_manifest_states',sa.Column('novel_id',sa.Integer(),sa.ForeignKey('novels.id',ondelete='CASCADE'),primary_key=True),
        sa.Column('manifest_epoch',sa.String(36),nullable=False,unique=True),sa.Column('revision',sa.BigInteger(),nullable=False,server_default='0'),
        sa.Column('identity_required',sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column('ao3_material',sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column('metadata_source',sa.JSON()),sa.Column('metadata_manifest_key',sa.String(36)),
        sa.Column('metadata_revision',sa.String(64)),sa.Column('metadata_fingerprint',sa.String(64)))
    op.create_table('chapter_manifest_reviews',*_timestamps(),sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('novel_id',sa.Integer(),sa.ForeignKey('novels.id',ondelete='CASCADE'),nullable=False),sa.Column('review_key',sa.String(36),nullable=False,unique=True),
        sa.Column('status',sa.String(20),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),sa.Column('fingerprint',sa.String(64),nullable=False),
        sa.Column('plan',sa.JSON(),nullable=False),sa.Column('before_state',sa.JSON()),sa.Column('after_fingerprint',sa.String(64)),
        sa.Column('expires_at',sa.DateTime(),nullable=False),sa.Column('applied_at',sa.DateTime()),sa.Column('undone_at',sa.DateTime()))
    for field in ('id','user_id','novel_id'):op.create_index(f'ix_chapter_manifest_reviews_{field}','chapter_manifest_reviews',[field])
    op.create_table('chapter_manifest_operations',*_timestamps(),sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('novel_id',sa.Integer(),sa.ForeignKey('novels.id',ondelete='CASCADE'),nullable=False),sa.Column('operation_id',sa.String(128),nullable=False),
        sa.Column('fingerprint',sa.String(64),nullable=False),sa.Column('response',sa.JSON(),nullable=False),sa.UniqueConstraint('user_id','operation_id',name='uq_chapter_manifest_operation'))
    op.create_index('ix_chapter_manifest_operations_id','chapter_manifest_operations',['id'])
    op.create_table('chapter_manifest_review_items',*_timestamps(),sa.Column('review_id',sa.Integer(),sa.ForeignKey('chapter_manifest_reviews.id',ondelete='CASCADE'),nullable=False),
        sa.Column('ordinal',sa.Integer(),nullable=False),sa.Column('item_kind',sa.String(20),nullable=False),sa.Column('chapter_key',sa.String(36)),
        sa.Column('metadata_chapter_key',sa.String(36)),sa.Column('title',sa.String(1000)),sa.Column('detail',sa.JSON(),nullable=False),
        sa.UniqueConstraint('review_id','ordinal',name='uq_manifest_review_item_ordinal'))
    for field in ('id','review_id'):op.create_index(f'ix_chapter_manifest_review_items_{field}','chapter_manifest_review_items',[field])
    for column in [sa.Column('source_content_version',sa.String(64)),sa.Column('furthest_content_version',sa.String(64)),sa.Column('current_identity_inferred',sa.Boolean(),nullable=False,server_default=sa.false()),sa.Column('chapter_key',sa.String(36)),sa.Column('furthest_chapter_key',sa.String(36)),
        sa.Column('furthest_identity_inferred',sa.Integer(),nullable=False,server_default='0'),sa.Column('manifest_epoch',sa.String(36)),sa.Column('manifest_revision',sa.String(20))]:
        op.add_column('reading_progress',column)
    op.add_column('reading_history',sa.Column('verified_content_version',sa.String(64)))
    op.add_column('reading_history',sa.Column('verified_percent',sa.Integer(),nullable=False,server_default='0'))
    op.add_column('reading_history',sa.Column('chapter_key',sa.String(36)))
    op.add_column('reading_history',sa.Column('identity_inferred',sa.Boolean(),nullable=False,server_default=sa.false()))
    with op.batch_alter_table('reading_history') as batch:
        batch.drop_constraint('uq_reading_history_day_run',type_='unique')
    op.create_index('uq_reading_history_identity_day_run','reading_history',['user_id','novel_id','chapter_key','reading_date','reading_run_key'],unique=True,
        sqlite_where=sa.text('chapter_key IS NOT NULL'),postgresql_where=sa.text('chapter_key IS NOT NULL'))
    op.create_index('uq_reading_history_unbound_day_run','reading_history',['user_id','novel_id','chapter_number','reading_date','reading_run_key'],unique=True,
        sqlite_where=sa.text('chapter_key IS NULL'),postgresql_where=sa.text('chapter_key IS NULL'))
    for id in connection.execute(sa.text('SELECT id FROM chapters')).scalars().yield_per(500):
        connection.execute(sa.text('UPDATE chapters SET chapter_key=:key WHERE id=:id'),{'key':str(uuid4()),'id':id})
    op.add_column('reading_annotations',sa.Column('chapter_key',sa.String(36)))
    op.add_column('reading_annotations',sa.Column('chapter_number',sa.Integer()))
    op.add_column('chapter_versions',sa.Column('chapter_key',sa.String(36)))
    with op.batch_alter_table('chapter_versions') as batch:
        batch.drop_constraint('uq_chapter_version',type_='unique')
        batch.create_unique_constraint('uq_chapter_identity_version',['chapter_key','content_version'])
    op.add_column('chapter_read_receipts',sa.Column('chapter_key',sa.String(36)))
    with op.batch_alter_table('chapter_read_receipts') as batch:
        batch.drop_constraint('uq_chapter_read_version',type_='unique')
        batch.create_unique_constraint('uq_chapter_read_identity_version',['user_id','chapter_key','content_version'])
    from app.models.chapter_manifest import install
    install(connection)
    # Historical notes retain their text, FK and locator for explicit recovery.
    # Neither a lifecycle UUID nor an original numeric label was captured; a
    # current FK lookup could borrow both from an unrelated replacement.
    connection.execute(sa.text('UPDATE reading_annotations SET chapter_key=NULL,chapter_number=NULL'))
    connection.execute(sa.text('UPDATE chapter_versions SET chapter_key=(SELECT c.chapter_key FROM chapters c WHERE c.id=chapter_versions.chapter_id)'))
    connection.execute(sa.text('UPDATE chapter_read_receipts SET chapter_key=NULL,requires_review=true'))
    # Number-only history is retained as inferred provenance, never promoted
    # into a genuine identity-based reading receipt by this migration.
    connection.execute(sa.text('UPDATE reading_history SET chapter_key=(SELECT c.chapter_key FROM chapters c WHERE c.novel_id=reading_history.novel_id AND c.chapter_number=reading_history.chapter_number), identity_inferred=true'))
    connection.execute(sa.text('UPDATE reading_progress SET chapter_key=(SELECT c.chapter_key FROM chapters c WHERE c.id=reading_progress.chapter_id AND c.novel_id=reading_progress.novel_id)'))
    connection.execute(sa.text('UPDATE reading_progress SET current_identity_inferred=true WHERE chapter_key IS NOT NULL OR chapter_number IS NOT NULL'))
    connection.execute(sa.text('UPDATE reading_progress SET furthest_chapter_key=(SELECT c.chapter_key FROM chapters c WHERE c.novel_id=reading_progress.novel_id AND c.chapter_number=reading_progress.furthest_chapter_number) WHERE furthest_chapter_number<>0 OR furthest_percent>0'))
    connection.execute(sa.text('UPDATE reading_progress SET furthest_identity_inferred=CASE WHEN furthest_chapter_key IS NOT NULL OR furthest_chapter_number<>0 OR furthest_percent>0 THEN 1 ELSE 0 END'))
    # A numeric FK and a body hash do not prove which historical source lifecycle
    # the old reader saw. Keep locator_content_version for visual recovery only;
    # the new strong source-version columns intentionally remain NULL.
    connection.execute(sa.text("UPDATE reading_progress SET manifest_epoch=(SELECT s.manifest_epoch FROM chapter_manifest_states s WHERE s.novel_id=reading_progress.novel_id),manifest_revision='0'"))


def downgrade():
    connection=op.get_bind()
    if connection.execute(sa.text('SELECT 1 FROM chapter_manifest_states WHERE identity_required=true LIMIT 1')).first() or connection.execute(sa.text('SELECT 1 FROM chapters WHERE archived=true LIMIT 1')).first():
        raise RuntimeError('Cannot remove stable identity fences after reviewed topology changes. Restore a complete pre-change backup instead; no originals or history were deleted.')
    duplicate=connection.execute(sa.text('SELECT 1 FROM chapters GROUP BY novel_id,chapter_number HAVING COUNT(*)>1 LIMIT 1')).first()
    if duplicate:
        raise RuntimeError('Cannot downgrade preserved chapter archives with duplicate historical ordinals. Undo topology changes first; no original content was deleted.')
    history_duplicate=connection.execute(sa.text('SELECT 1 FROM reading_history GROUP BY user_id,novel_id,chapter_number,reading_date,reading_run_key HAVING COUNT(*)>1 LIMIT 1')).first()
    if history_duplicate:
        raise RuntimeError('Cannot downgrade identity-specific history into ambiguous number-only history. Preserve a full backup; no reading records were deleted.')
    from app.models.chapter_manifest import uninstall
    uninstall(connection)
    if connection.execute(sa.text('SELECT 1 FROM chapter_read_receipts GROUP BY user_id,chapter_id,content_version HAVING COUNT(*)>1 LIMIT 1')).first():
        raise RuntimeError('Cannot collapse distinct chapter lifecycle receipts into reused numeric identities; no reading evidence was deleted.')
    if connection.execute(sa.text('SELECT 1 FROM chapter_versions GROUP BY chapter_id,content_version HAVING COUNT(*)>1 LIMIT 1')).first():
        raise RuntimeError('Cannot collapse originals from distinct chapter lifecycles; no original was deleted.')
    with op.batch_alter_table('chapter_versions') as batch:
        batch.drop_constraint('uq_chapter_identity_version',type_='unique');batch.drop_column('chapter_key')
        batch.create_unique_constraint('uq_chapter_version',['chapter_id','content_version'])
    with op.batch_alter_table('reading_annotations') as batch:
        batch.drop_column('chapter_key');batch.drop_column('chapter_number')
    with op.batch_alter_table('chapter_read_receipts') as batch:
        batch.drop_constraint('uq_chapter_read_identity_version',type_='unique');batch.drop_column('chapter_key')
        batch.create_unique_constraint('uq_chapter_read_version',['user_id','chapter_id','content_version'])
    op.drop_index('uq_reading_history_unbound_day_run',table_name='reading_history')
    op.drop_index('uq_reading_history_identity_day_run',table_name='reading_history')
    with op.batch_alter_table('reading_history') as batch:
        batch.drop_column('identity_inferred');batch.drop_column('chapter_key');batch.drop_column('verified_content_version');batch.drop_column('verified_percent')
        batch.create_unique_constraint('uq_reading_history_day_run',['user_id','novel_id','chapter_number','reading_date','reading_run_key'])
    with op.batch_alter_table('reading_progress') as batch:
        for name in ('manifest_revision','manifest_epoch','furthest_identity_inferred','furthest_chapter_key','chapter_key','current_identity_inferred','source_content_version','furthest_content_version'):batch.drop_column(name)
    op.drop_table('chapter_manifest_review_items');op.drop_table('chapter_manifest_operations');op.drop_table('chapter_manifest_reviews');op.drop_table('chapter_manifest_states')
    op.drop_index('uq_active_chapter_novel_number',table_name='chapters')
    with op.batch_alter_table('chapters') as batch:
        batch.drop_constraint('uq_chapter_lifecycle_key',type_='unique')
        for name in ('archived_at','archived','metadata_chapter_key','metadata_manifest_key','chapter_key'):batch.drop_column(name)
        batch.create_unique_constraint('uix_chapter_novel_number',['novel_id','chapter_number'])
