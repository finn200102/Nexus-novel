"""Private dynamic shelves and immutable filter-reference identities."""
from uuid import uuid4
from alembic import op
import sqlalchemy as sa

revision = '0047'
down_revision = '0046'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    for name in ('libraries', 'shelves'):
        op.add_column(name, sa.Column('identity_key', sa.String(36), nullable=True))
        table = sa.table(name, sa.column('id', sa.Integer()), sa.column('identity_key', sa.String(36)))
        last = 0
        while True:
            ids = bind.execute(sa.select(table.c.id).where(table.c.id > last).order_by(table.c.id).limit(250)).scalars().all()
            if not ids:
                break
            for id in ids:
                bind.execute(table.update().where(table.c.id == id).values(identity_key=str(uuid4())))
            last = ids[-1]
        op.create_index(f'uq_{name}_identity_key', name, ['identity_key'], unique=True)
    op.create_table('smart_shelves',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('created_at', sa.DateTime()), sa.Column('updated_at', sa.DateTime()),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('identity_key', sa.String(36), nullable=False),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('name_key', sa.String(360), nullable=False),
        sa.Column('definition', sa.JSON(), nullable=False), sa.Column('bindings', sa.JSON(), nullable=False),
        sa.Column('revision', sa.String(64), nullable=False),
        sa.UniqueConstraint('identity_key'),
        sa.UniqueConstraint('user_id', 'name_key', name='uq_smart_shelf_user_name'))
    op.create_index('ix_smart_shelves_id', 'smart_shelves', ['id'])
    op.create_index('ix_smart_shelves_user_id', 'smart_shelves', ['user_id'])


def downgrade():
    op.drop_table('smart_shelves')
    for name in ('shelves', 'libraries'):
        op.drop_index(f'uq_{name}_identity_key', table_name=name)
        op.drop_column(name, 'identity_key')
