"""Contentstatus

Revision ID: 9491914a5675
Revises: 8b0628939ca4
Create Date: 2025-03-20 13:40:45.455564

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9491914a5675'
down_revision: Union[str, None] = '8b0628939ca4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create the enum type using PostgreSQL-specific commands
    contentstatus = sa.Enum('missing', 'present', 'processing', name='contentstatus')
    contentstatus.create(op.get_bind())

    # Add the content_status column with default value
    op.add_column('chapters', 
                  sa.Column('content_status', 
                            sa.Enum('missing', 'present', 'processing', name='contentstatus'),
                            server_default='missing',
                            nullable=False))

    # Also change content column from String(255) to Text
    op.alter_column('chapters', 'content',
                    existing_type=sa.String(255),
                    type_=sa.Text(),
                    existing_nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    # Drop the content_status column
    op.drop_column('chapters', 'content_status')

    # Change content column back from Text to String(255)
    op.alter_column('chapters', 'content',
                    existing_type=sa.Text(),
                    type_=sa.String(255),
                    existing_nullable=True)

    # Drop the enum type using PostgreSQL-specific commands
    sa.Enum(name='contentstatus').drop(op.get_bind())
