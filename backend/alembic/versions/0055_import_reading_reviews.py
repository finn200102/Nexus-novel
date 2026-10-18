"""Retain imported reading material until exact chapter bindings are reviewed."""
from alembic import op
import sqlalchemy as sa
revision='0055'
down_revision='0054'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('import_reading_reviews',
        sa.Column('id',sa.Integer(),primary_key=True),sa.Column('created_at',sa.DateTime(),server_default=sa.func.now()),sa.Column('updated_at',sa.DateTime(),server_default=sa.func.now()),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('novel_id',sa.Integer(),sa.ForeignKey('novels.id',ondelete='CASCADE'),nullable=False),
        sa.Column('fingerprint',sa.String(64),nullable=False),sa.Column('revision',sa.Integer(),nullable=False),
        sa.Column('payload',sa.JSON(),nullable=False),sa.Column('applied_refs',sa.JSON(),nullable=False),sa.Column('preview',sa.JSON()),
        sa.UniqueConstraint('user_id','novel_id','fingerprint',name='uq_import_reading_document_story'))
    op.create_index('ix_import_reading_reviews_id','import_reading_reviews',['id'])
    op.create_index('ix_import_reading_reviews_user_id','import_reading_reviews',['user_id'])
    op.create_index('ix_import_reading_reviews_novel_id','import_reading_reviews',['novel_id'])
    op.create_table('import_reading_operations',
        sa.Column('id',sa.Integer(),primary_key=True),sa.Column('created_at',sa.DateTime(),server_default=sa.func.now()),sa.Column('updated_at',sa.DateTime(),server_default=sa.func.now()),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('review_id',sa.Integer(),sa.ForeignKey('import_reading_reviews.id',ondelete='CASCADE'),nullable=False),
        sa.Column('operation_id',sa.String(128),nullable=False),sa.Column('fingerprint',sa.String(64),nullable=False),sa.Column('response',sa.JSON(),nullable=False),
        sa.UniqueConstraint('user_id','operation_id',name='uq_import_reading_operation'))
    op.create_index('ix_import_reading_operations_id','import_reading_operations',['id'])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT 1 FROM import_reading_reviews LIMIT 1')).first():
        raise RuntimeError('Export unresolved imported reading material before downgrading.')
    op.drop_table('import_reading_operations')
    op.drop_table('import_reading_reviews')
