"""Durable import jobs and their per-item report.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-08 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0008'
down_revision: Union[str, Sequence[str], None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'import_jobs',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('library_id', sa.Integer(), nullable=False),
        sa.Column('source', sa.String(length=32), nullable=False),
        sa.Column('params', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='queued', nullable=False),
        sa.Column('next_page', sa.Integer(), nullable=True),
        sa.Column('total_items', sa.Integer(), server_default='0', nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['library_id'], ['libraries.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('import_jobs', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_import_jobs_id'), ['id'], unique=False)
        batch_op.create_index(batch_op.f('ix_import_jobs_user_id'), ['user_id'], unique=False)

    op.create_table(
        'import_job_items',
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('url', sa.String(length=500), nullable=True),
        sa.Column('label', sa.String(length=500), nullable=True),
        sa.Column('title', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=20), server_default='queued', nullable=False),
        sa.Column('reason', sa.Text(), nullable=True),
        sa.Column('novel_id', sa.Integer(), nullable=True),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['job_id'], ['import_jobs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['novel_id'], ['novels.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('import_job_items', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_import_job_items_id'), ['id'], unique=False)
        batch_op.create_index('ix_import_job_items_job_status', ['job_id', 'status'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('import_job_items', schema=None) as batch_op:
        batch_op.drop_index('ix_import_job_items_job_status')
        batch_op.drop_index(batch_op.f('ix_import_job_items_id'))
    op.drop_table('import_job_items')
    with op.batch_alter_table('import_jobs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_import_jobs_user_id'))
        batch_op.drop_index(batch_op.f('ix_import_jobs_id'))
    op.drop_table('import_jobs')
