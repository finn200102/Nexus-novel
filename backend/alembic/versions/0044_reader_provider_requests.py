"""Per-request paid reservations, legacy outstanding balances and retry fences."""
from uuid import uuid4
from datetime import datetime, UTC
from alembic import op
import sqlalchemy as sa

revision = '0044'
down_revision = '0043'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('translation_jobs', sa.Column('paid_retry_generation', sa.Integer(), nullable=False, server_default='0'))
    op.create_table('reader_provider_requests',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('created_at', sa.DateTime()), sa.Column('updated_at', sa.DateTime()),
        sa.Column('request_key', sa.String(36), nullable=False, unique=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider_id', sa.Integer(), sa.ForeignKey('reader_providers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('model_snapshot', sa.JSON(), nullable=False), sa.Column('status', sa.String(24), nullable=False),
        sa.Column('revision', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('reserved_microusd', sa.BigInteger(), nullable=False), sa.Column('actual_microusd', sa.BigInteger()),
        sa.Column('input_tokens', sa.BigInteger()), sa.Column('output_tokens', sa.BigInteger()),
        sa.Column('expires_at', sa.DateTime()), sa.Column('resolved_at', sa.DateTime()),
        sa.Column('translation_job_id', sa.Integer()), sa.Column('translation_block_index', sa.Integer()), sa.Column('retry_generation', sa.Integer()),
        sa.UniqueConstraint('translation_job_id', 'translation_block_index', 'retry_generation', name='uq_paid_translation_dispatch'))
    for column in ('id', 'user_id', 'provider_id'):
        op.create_index(f'ix_reader_provider_requests_{column}', 'reader_provider_requests', [column])
    op.create_table('reader_provider_reconciliation_operations',
        sa.Column('id', sa.Integer(), primary_key=True), sa.Column('created_at', sa.DateTime()), sa.Column('updated_at', sa.DateTime()),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('provider_id', sa.Integer(), sa.ForeignKey('reader_providers.id', ondelete='CASCADE'), nullable=False),
        sa.Column('operation_id', sa.String(128), nullable=False), sa.Column('fingerprint', sa.String(64), nullable=False), sa.Column('response', sa.JSON(), nullable=False),
        sa.UniqueConstraint('user_id', 'operation_id', name='uq_provider_reconciliation_operation'))
    op.create_index('ix_reader_provider_reconciliation_operations_id', 'reader_provider_reconciliation_operations', ['id'])
    bind = op.get_bind()
    providers = sa.Table('reader_providers', sa.MetaData(), autoload_with=bind)
    ledger = sa.Table('reader_provider_requests', sa.MetaData(), autoload_with=bind)
    jobs = sa.Table('translation_jobs', sa.MetaData(), autoload_with=bind)
    paid_ids = sa.select(providers.c.id).where(providers.c.kind.notin_(['local', 'local_translation']))
    # Existing paid processing may have committed billing just before losing its
    # paragraph, even when no aggregate reserve remains. Never infer it is safe
    # to resume across this upgrade without explicit reader review.
    bind.execute(jobs.update().where(jobs.c.provider_id.in_(paid_ids),
        jobs.c.status.in_(['processing', 'retry_wait'])).values(status='failed',
        error_code='LEGACY_PAID_REVIEW_REQUIRED',
        error='Paid processing was interrupted before request tracking. Review provider charges and reconcile legacy reservations before explicitly retrying.',
        finished_at=datetime.now(UTC).replace(tzinfo=None), lease_owner=None, lease_expires_at=None, next_attempt_at=None))
    # Preserve the original used/reserved balances exactly. Legacy reservations
    # cannot reveal token usage, original model or dispatch dates retrospectively.
    last_id = 0
    while True:
        rows = bind.execute(sa.select(providers).where(providers.c.id > last_id, providers.c.reserved_microusd > 0).order_by(providers.c.id).limit(250)).mappings().all()
        if not rows:
            break
        for row in rows:
            now = datetime.now(UTC).replace(tzinfo=None)
            bind.execute(ledger.insert().values(request_key=str(uuid4()), user_id=row['user_id'], provider_id=row['id'],
                model_snapshot={'kind': 'legacy_unknown', 'base_url': '', 'model': 'Unknown legacy request', 'input_price': None, 'output_price': None},
                status='legacy_unknown', revision=0, reserved_microusd=row['reserved_microusd'], created_at=now, updated_at=now))
        last_id = rows[-1]['id']


def downgrade():
    op.drop_table('reader_provider_reconciliation_operations')
    op.drop_table('reader_provider_requests')
    op.drop_column('translation_jobs', 'paid_retry_generation')
