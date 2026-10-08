"""Usernames are unique case-insensitively.

Refuses to run while two accounts differ only by case: those must be
resolved by an administrator first (usernames are never renamed silently).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-08 16:00:00.000000

"""
from collections import defaultdict
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0010'
down_revision: Union[str, Sequence[str], None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = 'ux_users_username_lower'


def _duplicate_usernames(bind) -> dict[str, list[str]]:
    rows = bind.execute(sa.text("SELECT id, username FROM users ORDER BY id")).all()
    groups: dict[str, list[str]] = defaultdict(list)
    for _, username in rows:
        groups[username.lower()].append(username)
    return {key: names for key, names in groups.items() if len(names) > 1}


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    duplicates = _duplicate_usernames(bind)
    if duplicates:
        lines = [f"  - {' / '.join(repr(name) for name in names)}" for names in duplicates.values()]
        raise RuntimeError(
            "Cannot make usernames case-insensitively unique: these accounts differ only by case. "
            "Rename or merge them (for example with an administrator), then run the migration again:\n"
            + "\n".join(lines)
        )
    op.create_index(INDEX_NAME, 'users', [sa.text('lower(username)')], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(INDEX_NAME, table_name='users')
