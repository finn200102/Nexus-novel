"""Preserve an unset companion choice when granting only translation access."""
from alembic import op
import sqlalchemy as sa

revision='0042'
down_revision='0041'
branch_labels=None
depends_on=None


def upgrade():
    with op.batch_alter_table('story_processing_permissions') as batch:
        batch.alter_column('companion',existing_type=sa.Boolean(),existing_nullable=False,nullable=True)


def downgrade():
    # Older versions cannot represent unset. Restore their conservative denial;
    # never turn an absent choice into permission during a downgrade.
    op.execute(sa.text('UPDATE story_processing_permissions SET companion=false WHERE companion IS NULL'))
    with op.batch_alter_table('story_processing_permissions') as batch:
        batch.alter_column('companion',existing_type=sa.Boolean(),existing_nullable=True,nullable=False)
