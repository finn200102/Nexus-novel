"""Explicit private guide/image capabilities and generic request fencing."""
from alembic import op
import sqlalchemy as sa
revision = '0051'
down_revision = '0050'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("story_processing_permissions") as batch:
        batch.alter_column("translation", existing_type=sa.Boolean(), nullable=True)
    for column in [sa.Column('capabilities', sa.JSON(), nullable=True), sa.Column('image_model', sa.String(255)),
        sa.Column('image_price_microusd', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('image_sizes', sa.JSON(), nullable=False, server_default='[]'),
        sa.Column('image_qualities', sa.JSON(), nullable=False, server_default='[]')]:
        op.add_column('reader_providers', column)
    for column in [sa.Column('portrait', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('portrait_ao3_consent', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('portrait_provider_snapshot', sa.JSON(), nullable=True)]:
        op.add_column('story_processing_permissions', column)
    for column in [sa.Column('purpose', sa.String(32)), sa.Column('job_key', sa.String(64)), sa.Column('item_key', sa.String(120))]:
        op.add_column('reader_provider_requests', column)
    op.create_index('uq_provider_work_dispatch', 'reader_provider_requests', ['user_id', 'purpose', 'job_key', 'item_key', 'retry_generation'], unique=True)


def downgrade():
    # An older server cannot represent undecided translation grants; fail closed.
    op.execute(sa.text("UPDATE story_processing_permissions SET translation=false WHERE translation IS NULL"))
    with op.batch_alter_table("story_processing_permissions") as batch:
        batch.alter_column("translation", existing_type=sa.Boolean(), nullable=False)
    op.drop_index('uq_provider_work_dispatch', table_name='reader_provider_requests')
    for table, columns in [('reader_provider_requests', ['item_key', 'job_key', 'purpose']),
        ('story_processing_permissions', ['portrait_provider_snapshot', 'portrait_ao3_consent', 'portrait']),
        ('reader_providers', ['image_qualities', 'image_sizes', 'image_price_microusd', 'image_model', 'capabilities'])]:
        with op.batch_alter_table(table) as batch:
            for name in columns: batch.drop_column(name)
