"""Private provider-controlled reading guides and portraits."""
from alembic import op
import sqlalchemy as sa
revision = '0050'
down_revision = '0049'
branch_labels = None
depends_on = None


def upgrade():
    common = lambda: [sa.Column('id', sa.Integer(), primary_key=True), sa.Column('created_at', sa.DateTime()), sa.Column('updated_at', sa.DateTime())]
    op.create_table('private_guide_jobs', *common(),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('novel_id', sa.Integer(), sa.ForeignKey('novels.id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider_id', sa.Integer(), sa.ForeignKey('reader_providers.id'), nullable=False),
        sa.Column('job_key', sa.String(36), nullable=False, unique=True),
        sa.Column('reading_run_key', sa.String(36), nullable=False), sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('status', sa.String(24), nullable=False), sa.Column('revision', sa.Integer(), nullable=False),
        sa.Column('cache_key', sa.String(64), nullable=False), sa.Column('fingerprint', sa.String(64), nullable=False), sa.Column('review', sa.JSON(), nullable=False),
        sa.Column('completed_steps', sa.Integer(), nullable=False), sa.Column('total_steps', sa.Integer(), nullable=False),
        sa.Column('retry_generation', sa.Integer(), nullable=False), sa.Column('lease_owner', sa.String(36)),
        sa.Column('lease_expires_at', sa.DateTime()), sa.Column('error_code', sa.String(80)), sa.Column('error', sa.Text()),
        sa.Column('charged_microusd', sa.BigInteger(), nullable=False),
        sa.UniqueConstraint('user_id', 'cache_key', name='uq_private_guide_result_cache'))
    op.create_index('ix_private_guide_jobs_cache_key', 'private_guide_jobs', ['cache_key'])
    op.create_table('private_guide_artifacts', *common(),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('novel_id', sa.Integer(), sa.ForeignKey('novels.id', ondelete='CASCADE'), nullable=False),
        sa.Column('job_id', sa.Integer(), sa.ForeignKey('private_guide_jobs.id', ondelete='CASCADE'), nullable=False),
        sa.Column('step', sa.Integer(), nullable=False), sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('content', sa.JSON(), nullable=False), sa.Column('citations', sa.JSON(), nullable=False),
        sa.Column('media_data', sa.LargeBinary()), sa.Column('media_type', sa.String(80)),
        sa.UniqueConstraint('job_id', 'step', name='uq_private_guide_step'))
    op.create_table('private_guide_operations', *common(),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('operation_id', sa.String(128), nullable=False), sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('response', sa.JSON(), nullable=False),
        sa.UniqueConstraint('user_id', 'operation_id', name='uq_private_guide_operation'))
    for table in ('private_guide_jobs', 'private_guide_artifacts', 'private_guide_operations'):
        op.create_index('ix_' + table + '_id', table, ['id'])
    for table in ('private_guide_jobs', 'private_guide_artifacts'):
        for column in ('user_id', 'novel_id'):
            op.create_index('ix_' + table + '_' + column, table, [column])


def downgrade():
    for table in ('private_guide_artifacts', 'private_guide_operations', 'private_guide_jobs'):
        op.drop_table(table)
