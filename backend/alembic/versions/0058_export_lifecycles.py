"""Fence external highlight acknowledgements against row replacement."""
from alembic import op
import sqlalchemy as sa
revision='0058'
down_revision='0057'
branch_labels=None
depends_on=None


def upgrade():
    from app.models.export_lifecycle import install
    connection=op.get_bind()
    for table in ('reading_annotations','readwise_connections'):
        op.add_column(table,sa.Column('export_key',sa.String(36),nullable=True))
        expr='lower(hex(randomblob(16)))' if connection.dialect.name=='sqlite' else 'gen_random_uuid()::text'
        connection.execute(sa.text(f'UPDATE {table} SET export_key={expr} WHERE export_key IS NULL'))
        op.create_index('uq_'+table+'_export_key',table,['export_key'],unique=True)
        install(connection,table)


def downgrade():
    connection=op.get_bind()
    for table in ('readwise_connections','reading_annotations'):
        if connection.dialect.name=='sqlite':
            for suffix in ('insert','immutable'):connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS {table}_export_key_{suffix}')
        else:
            connection.exec_driver_sql(f'DROP TRIGGER IF EXISTS {table}_export_key_guard ON {table}')
            connection.exec_driver_sql(f'DROP FUNCTION IF EXISTS {table}_export_key_fn()')
        op.drop_index('uq_'+table+'_export_key',table_name=table)
        op.drop_column(table,'export_key')
