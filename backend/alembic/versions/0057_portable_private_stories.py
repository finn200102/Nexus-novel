"""Keep private URL-less stories portable without inventing a source address."""
from alembic import op
import sqlalchemy as sa
revision='0057'
down_revision='0056'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('portable_story_links',
        sa.Column('id',sa.Integer(),primary_key=True),sa.Column('created_at',sa.DateTime()),sa.Column('updated_at',sa.DateTime()),
        sa.Column('user_id',sa.Integer(),sa.ForeignKey('users.id',ondelete='CASCADE'),nullable=False),
        sa.Column('library_id',sa.Integer(),sa.ForeignKey('libraries.id',ondelete='CASCADE'),nullable=False),
        sa.Column('destination_account_key',sa.String(36),nullable=False),sa.Column('destination_library_key',sa.String(36),nullable=False),
        sa.Column('source_account_key',sa.String(36),nullable=False),sa.Column('source_story_epoch',sa.String(36),nullable=False),
        sa.Column('novel_id',sa.Integer(),sa.ForeignKey('novels.id',ondelete='SET NULL')),
        sa.Column('target_story_epoch',sa.String(36),nullable=False),sa.Column('pending_payload',sa.JSON()),
        sa.UniqueConstraint('user_id','library_id','source_account_key','source_story_epoch',name='uq_portable_story_origin_destination'))
    for field in ('id','user_id','library_id','novel_id'):op.create_index('ix_portable_story_links_'+field,'portable_story_links',[field])


def downgrade():
    if op.get_bind().execute(sa.text('SELECT 1 FROM portable_story_links LIMIT 1')).first():
        raise RuntimeError('Export private portable story links before downgrading; deleting them would lose repeat-import identity.')
    op.drop_table('portable_story_links')
