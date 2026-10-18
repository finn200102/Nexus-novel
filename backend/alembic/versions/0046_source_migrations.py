"""Private reviewed reading-source transfers and idempotent undo receipts."""
from alembic import op
import sqlalchemy as sa
revision = '0046'
down_revision = '0045'
branch_labels = None
depends_on = None


def base():
    return [sa.Column('id', sa.Integer(), primary_key=True), sa.Column('created_at', sa.DateTime()), sa.Column('updated_at', sa.DateTime())]


def upgrade():
    op.create_table('source_migrations', *base(),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_novel_id', sa.Integer(), sa.ForeignKey('novels.id', ondelete='SET NULL'), nullable=True),
        sa.Column('target_novel_id', sa.Integer(), sa.ForeignKey('novels.id', ondelete='SET NULL'), nullable=True),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('status', sa.String(20), nullable=False, server_default='applied'),
        sa.Column('plan', sa.JSON(), nullable=False), sa.Column('counts', sa.JSON(), nullable=False),
        sa.Column('created_rows', sa.JSON(), nullable=False), sa.Column('target_guard', sa.String(64), nullable=False),
        sa.Column('undone_at', sa.DateTime()))
    op.create_table('source_migration_operations', *base(),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('migration_id', sa.Integer(), sa.ForeignKey('source_migrations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('operation_id', sa.String(128), nullable=False), sa.Column('fingerprint', sa.String(64), nullable=False),
        sa.Column('response', sa.JSON(), nullable=False),
        sa.UniqueConstraint('user_id', 'operation_id', name='uq_source_migration_operation'))
    for table, columns in [('source_migrations', ('id', 'user_id', 'source_novel_id', 'target_novel_id')),
                           ('source_migration_operations', ('id', 'user_id', 'migration_id'))]:
        for column in columns:
            op.create_index(f'ix_{table}_{column}', table, [column])


def downgrade():
    op.drop_table('source_migration_operations')
    op.drop_table('source_migrations')
