"""Permanent browser-storage identities survive upgrades and restore."""
from uuid import uuid4
from alembic import op
import sqlalchemy as sa

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("storage_id", sa.String(36), nullable=True))
    connection = op.get_bind()
    for user_id in connection.execute(sa.text("SELECT id FROM users")).scalars().all():
        connection.execute(sa.text("UPDATE users SET storage_id = :identity WHERE id = :id"),
                           {"identity": str(uuid4()), "id": user_id})
    with op.batch_alter_table("users") as batch:
        batch.alter_column("storage_id", existing_type=sa.String(36), nullable=False)
        batch.create_unique_constraint("uq_users_storage_id", ["storage_id"])


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_storage_id", type_="unique")
        batch.drop_column("storage_id")
