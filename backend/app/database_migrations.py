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

        connection.execute(text("""
            UPDATE novels
            SET follow_state = CASE follow_state
                WHEN 'following' THEN 'plan_to_read'
                WHEN 'muted' THEN 'on_hold'
                WHEN 'unfollowed' THEN 'ignored'
                ELSE follow_state
            END
            WHERE follow_state IN ('following', 'muted', 'unfollowed')
        """))

        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS user_novel_follows (
                id INTEGER PRIMARY KEY,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                novel_id INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
                state VARCHAR(20) NOT NULL DEFAULT 'plan_to_read',
                followed_at TIMESTAMP NULL,
                download_policy VARCHAR(20) NOT NULL DEFAULT 'none',
                download_count INTEGER NOT NULL DEFAULT 0,
                notification_policy VARCHAR(20) NOT NULL DEFAULT 'immediate',
                CONSTRAINT uq_user_novel_follow UNIQUE (user_id, novel_id)
            )
        """))
        follow_columns = {column["name"] for column in inspect(engine).get_columns("user_novel_follows")}
        follow_additions = {
            "download_policy": "VARCHAR(20) NOT NULL DEFAULT 'none'",
            "download_count": "INTEGER NOT NULL DEFAULT 0",
            "notification_policy": "VARCHAR(20) NOT NULL DEFAULT 'immediate'",
        }
        for name, definition in follow_additions.items():
            if name not in follow_columns:
                connection.execute(text(f"ALTER TABLE user_novel_follows ADD COLUMN {name} {definition}"))
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS novel_update_events (
                id INTEGER PRIMARY KEY,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                novel_id INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
                event_type VARCHAR(40) NOT NULL,
                chapter_count INTEGER NOT NULL DEFAULT 0,
                first_chapter_number INTEGER NULL,
                last_chapter_number INTEGER NULL,
                message TEXT NOT NULL DEFAULT '',
                details JSON NOT NULL DEFAULT '{}',
                read_at TIMESTAMP NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS chapter_download_jobs (
                id INTEGER PRIMARY KEY,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                library_id INTEGER NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
                novel_id INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
                chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
                status VARCHAR(20) NOT NULL DEFAULT 'queued',
                attempt_count INTEGER NOT NULL DEFAULT 0,
                error TEXT NULL
            )
        """))
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS reading_progress (
                id INTEGER PRIMARY KEY,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                novel_id INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
                chapter_id INTEGER NULL REFERENCES chapters(id) ON DELETE SET NULL,
                chapter_number INTEGER NULL,
                position INTEGER NOT NULL DEFAULT 0,
                percent FLOAT NOT NULL DEFAULT 0,
                CONSTRAINT uq_user_novel_progress UNIQUE (user_id, novel_id)
            )
        """))
