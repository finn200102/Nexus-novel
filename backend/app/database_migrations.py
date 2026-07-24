"""Small compatibility migrations for existing Nexus Novel installations.

The project predates Alembic, so these additive migrations keep deployed
PostgreSQL and local SQLite databases compatible with new model fields.
"""

from sqlalchemy import inspect, text


def ensure_runtime_schema(engine) -> None:
    inspector = inspect(engine)
    if "novels" not in inspector.get_table_names():
        return

    integer_primary_key = "SERIAL PRIMARY KEY" if engine.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    boolean_default = "TRUE" if engine.dialect.name == "postgresql" else "1"

    existing_columns = {column["name"] for column in inspector.get_columns("novels")}
    additions = {
        "follow_state": "VARCHAR(20) NOT NULL DEFAULT 'following'",
        "followed_at": "TIMESTAMP NULL",
    }
    with engine.begin() as connection:
        user_columns = {column["name"] for column in inspect(engine).get_columns("users")}
        if "is_admin" not in user_columns:
            connection.execute(text(f"ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT {boolean_default.replace('TRUE', 'FALSE')}"))
        connection.execute(text(f"UPDATE users SET is_admin = {boolean_default} WHERE id = (SELECT MIN(id) FROM users)"))
        # Early Nexus Novel versions made metadata_id globally unique. Catalog
        # metadata is shared, but library membership is per-library, so remove
        # that constraint before accepting the same work in another library.
        if engine.dialect.name == "postgresql":
            connection.execute(text("ALTER TABLE novels DROP CONSTRAINT IF EXISTS novels_metadata_id_key"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_novels_metadata_id ON novels (metadata_id)"))
            connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_novels_library_url ON novels (library_id, url)"))
        for name, definition in additions.items():
            if name not in existing_columns:
                connection.execute(text(f"ALTER TABLE novels ADD COLUMN {name} {definition}"))

        connection.execute(text(f"""
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
                notification_count INTEGER NOT NULL DEFAULT 1,
                CONSTRAINT uq_user_novel_follow UNIQUE (user_id, novel_id)
            )
        """))
        follow_columns = {column["name"] for column in inspect(engine).get_columns("user_novel_follows")}
        follow_additions = {
            "download_policy": "VARCHAR(20) NOT NULL DEFAULT 'none'",
            "download_count": "INTEGER NOT NULL DEFAULT 0",
            "notification_policy": "VARCHAR(20) NOT NULL DEFAULT 'immediate'",
            "notification_count": "INTEGER NOT NULL DEFAULT 1",
        }
        for name, definition in follow_additions.items():
            if name not in follow_columns:
                connection.execute(text(f"ALTER TABLE user_novel_follows ADD COLUMN {name} {definition}"))
        connection.execute(text(f"""
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
                details JSON NOT NULL DEFAULT '{{}}',
                read_at TIMESTAMP NULL,
                notification_visible BOOLEAN NOT NULL DEFAULT {boolean_default}
            )
        """))
        connection.execute(text(f"""
            CREATE TABLE IF NOT EXISTS metadata_webhook_deliveries (
                id {integer_primary_key},
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                delivery_key VARCHAR(512) NOT NULL,
                source_job_id VARCHAR(255) NOT NULL,
                source_id INTEGER NOT NULL,
                event_type VARCHAR(80) NOT NULL,
                claimed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT uq_metadata_webhook_delivery_key UNIQUE (delivery_key)
            )
        """))
        event_columns = {column["name"] for column in inspect(engine).get_columns("novel_update_events")}
        if "notification_visible" not in event_columns:
            connection.execute(text(
                f"ALTER TABLE novel_update_events ADD COLUMN notification_visible BOOLEAN NOT NULL DEFAULT {boolean_default}"
            ))
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
                max_attempts INTEGER NOT NULL DEFAULT 3,
                next_attempt_at TIMESTAMP NULL,
                started_at TIMESTAMP NULL,
                finished_at TIMESTAMP NULL,
                last_attempt_at TIMESTAMP NULL,
                cancelled_at TIMESTAMP NULL,
                cancellation_reason TEXT NULL,
                error_code VARCHAR(80) NULL,
                error TEXT NULL
            )
        """))
        job_columns = {column["name"] for column in inspect(engine).get_columns("chapter_download_jobs")}
        job_additions = {
            "max_attempts": "INTEGER NOT NULL DEFAULT 3",
            "next_attempt_at": "TIMESTAMP NULL",
            "started_at": "TIMESTAMP NULL",
            "finished_at": "TIMESTAMP NULL",
            "last_attempt_at": "TIMESTAMP NULL",
            "cancelled_at": "TIMESTAMP NULL",
            "cancellation_reason": "TEXT NULL",
            "error_code": "VARCHAR(80) NULL",
        }
        for name, definition in job_additions.items():
            if name not in job_columns:
                connection.execute(text(f"ALTER TABLE chapter_download_jobs ADD COLUMN {name} {definition}"))
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
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS reading_annotations (
                id INTEGER PRIMARY KEY,
                created_at TIMESTAMP,
                updated_at TIMESTAMP,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                novel_id INTEGER NOT NULL REFERENCES novels(id) ON DELETE CASCADE,
                chapter_id INTEGER NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
                annotation_type VARCHAR(20) NOT NULL DEFAULT 'bookmark',
                position INTEGER NOT NULL DEFAULT 0,
                percent FLOAT NOT NULL DEFAULT 0,
                quote TEXT NULL,
                note TEXT NULL
            )
        """))
