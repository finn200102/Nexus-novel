"""Single sign-on identity on users.

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-09 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0016'
down_revision: Union[str, Sequence[str], None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.add_column(sa.Column('oidc_issuer', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('oidc_subject', sa.String(length=255), nullable=True))
        batch_op.create_unique_constraint('uq_users_oidc_identity', ['oidc_issuer', 'oidc_subject'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.drop_constraint('uq_users_oidc_identity', type_='unique')
        batch_op.drop_column('oidc_subject')
        batch_op.drop_column('oidc_issuer')
