"""Preserve fractional source ratings without changing personal ratings."""
from alembic import op
import sqlalchemy as sa

revision = '0060'
down_revision = '0059'
branch_labels = None
depends_on = None


def upgrade():
    # SQLite already stores fractional values in INTEGER-affinity columns.
    # Avoid rebuilding novels and disturbing its chapter identity triggers.
    if op.get_bind().dialect.name == 'sqlite':
        return
    op.alter_column('novels', 'rating', existing_type=sa.Integer(), type_=sa.Float(),
        existing_nullable=True)


def downgrade():
    if op.get_bind().dialect.name == 'sqlite':
        return
    op.alter_column('novels', 'rating', existing_type=sa.Float(), type_=sa.Integer(),
        existing_nullable=True, postgresql_using='rating::integer')
