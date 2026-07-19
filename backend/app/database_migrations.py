"""Small compatibility migrations for existing Nexus Novel installations.

The project predates Alembic, so these additive migrations keep deployed
PostgreSQL and local SQLite databases compatible with new model fields.
"""

from sqlalchemy import inspect, text


def ensure_runtime_schema(engine) -> None:
    inspector = inspect(engine)
    if "novels" not in inspector.get_table_names():
        return

    existing_columns = {column["name"] for column in inspector.get_columns("novels")}
    additions = {
        "follow_state": "VARCHAR(20) NOT NULL DEFAULT 'following'",
        "followed_at": "TIMESTAMP NULL",
    }
    with engine.begin() as connection:
        for name, definition in additions.items():
            if name not in existing_columns:
                connection.execute(text(f"ALTER TABLE novels ADD COLUMN {name} {definition}"))
