"""Bring the Nexus Novel database to the current Alembic head.

``upgrade_database`` runs on every API and worker start:

* empty database: ``upgrade head`` creates the whole schema;
* pre-Alembic database (application tables but no ``alembic_version``): the
  legacy compatibility step below applies what the old start-up code and the
  hand-run ``migrations/*.sql`` scripts did, the baseline revision fills in
  any table that installation never had, and Alembic records the baseline;
  then ``upgrade head`` continues as usual;
* Alembic database: ``upgrade head``.

On PostgreSQL the whole run holds an advisory lock, so the API and the worker
can start at the same time: the second process waits, then finds the schema
at head and does nothing.
"""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Connection, Engine

from app.logging_config import get_logger

logger = get_logger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[1]
BASELINE_REVISION = "0001"
# Arbitrary, fixed key for pg_advisory_lock ("nexus-novel" as an integer).
MIGRATION_LOCK_KEY = 0x6E6F76656C

# Tables that only an existing Nexus Novel installation would have.
LEGACY_MARKER_TABLES = {"users", "libraries", "novels"}


def alembic_config(connection: Connection | None = None) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    # The application configures logging itself.
    config.attributes["configure_logger"] = False
    if connection is not None:
        config.attributes["connection"] = connection
    return config


def upgrade_database(engine: Engine) -> None:
    with engine.connect() as connection:
        postgres = connection.dialect.name == "postgresql"
        if postgres:
            connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": MIGRATION_LOCK_KEY})
            connection.commit()
        try:
            _upgrade(connection)
        finally:
            if postgres:
                connection.rollback()
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": MIGRATION_LOCK_KEY})
                connection.commit()


def _upgrade(connection: Connection) -> None:
    tables = set(inspect(connection).get_table_names())
    config = alembic_config(connection)
    if "alembic_version" not in tables and tables & LEGACY_MARKER_TABLES:
        logger.info("database_legacy_upgrade_started")
        legacy_compat(connection)
        connection.commit()
        # The baseline only creates missing tables, so on an existing
        # installation running it is the same as stamping it.
        command.upgrade(config, BASELINE_REVISION)
        connection.commit()
        logger.info("database_legacy_upgrade_finished", revision=BASELINE_REVISION)
    command.upgrade(config, "head")
    connection.commit()


def _columns(connection: Connection, table: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table)}


def _add_missing_columns(connection: Connection, table: str, columns: dict[str, str]) -> None:
    existing = _columns(connection, table)
    for name, definition in columns.items():
        if name not in existing:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))


def _add_unique_constraint(connection: Connection, table: str, name: str, columns: str) -> None:
    """PostgreSQL only. Replaces a plain unique index of the same name, which
    some older start-up code created instead of the model's constraint."""
    if connection.execute(text("SELECT 1 FROM pg_constraint WHERE conname = :name"), {"name": name}).first():
        return
    connection.execute(text(f"DROP INDEX IF EXISTS {name}"))
    connection.execute(text(f"ALTER TABLE {table} ADD CONSTRAINT {name} UNIQUE ({columns})"))


def legacy_compat(connection: Connection) -> None:
    """Upgrade a pre-Alembic installation to the baseline schema.

    Runs once, before the database is stamped. It covers the ad-hoc ALTERs the
    API used to run on every start and ``backend/migrations/001-007.sql``.
    Tables that do not exist yet are left to the baseline revision.
    """
    postgres = connection.dialect.name == "postgresql"
    true = "TRUE" if postgres else "1"
    false = "FALSE" if postgres else "0"
    tables = set(inspect(connection).get_table_names())

    if "users" in tables:
        _add_missing_columns(connection, "users", {"is_admin": f"BOOLEAN NOT NULL DEFAULT {false}"})
        # Old versions promoted the first account to administrator on every
        # start. Do it one last time, only when nobody is an administrator,
        # so upgrading never leaves an instance without one.
        has_admin = connection.execute(text(f"SELECT 1 FROM users WHERE is_admin = {true} LIMIT 1")).first()
        if not has_admin:
            connection.execute(text(f"UPDATE users SET is_admin = {true} WHERE id = (SELECT MIN(id) FROM users)"))

    if "authors" in tables:
        _add_missing_columns(connection, "authors", {"site": "VARCHAR(50)"})

    if "novels" in tables:
        _add_missing_columns(connection, "novels", {
            "metadata_id": "INTEGER",
            "author": "VARCHAR(255)",
            "author_site_id": "BIGINT",
            "source_url": "VARCHAR(500)",
            "story_id": "BIGINT",
            "novel_site": "VARCHAR(50)",
            "img_url": "VARCHAR(500)",
            "word_count": "INTEGER",
            "reviews": "INTEGER",
            "favorites": "INTEGER",
            "follows": "INTEGER",
            "status": "VARCHAR(50)",
            "views": "INTEGER",
            "rating": "INTEGER",
            "publish_date": "TIMESTAMP",
            "updated_date": "TIMESTAMP",
            "chapter_count": "INTEGER",
            "analyzed_at": "TIMESTAMP",
            "analysis_type": "VARCHAR(50)",
            "analyzed_chapter_count": "INTEGER",
            "parsed_at": "TIMESTAMP",
            "scrape_status": "VARCHAR(20)",
            "scrape_error": "VARCHAR(500)",
            "follow_state": "VARCHAR(20) NOT NULL DEFAULT 'plan_to_read'",
            "followed_at": "TIMESTAMP NULL",
        })
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
        if postgres:
            # Catalog metadata is shared, so the same work may sit in several
            # libraries; early versions made metadata_id globally unique.
            connection.execute(text("ALTER TABLE novels DROP CONSTRAINT IF EXISTS novels_metadata_id_key"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_novels_metadata_id ON novels (metadata_id)"))
            _add_unique_constraint(connection, "novels", "uq_novels_library_url", "library_id, url")
            for column in ("site_story_id", "story_id", "author_site_id"):
                connection.execute(text(f"ALTER TABLE novels ALTER COLUMN {column} TYPE BIGINT"))

    if "chapters" in tables:
        _add_missing_columns(connection, "chapters", {
            "source_url": "VARCHAR(500)",
            "word_count": "INTEGER",
            "download_started_at": "TIMESTAMP",
            "download_finished_at": "TIMESTAMP",
            "download_error": "VARCHAR(1000)",
            "retry_count": "INTEGER NOT NULL DEFAULT 0",
        })
        if postgres:
            connection.execute(text("ALTER TABLE chapters ALTER COLUMN site_chapter_id TYPE BIGINT"))

    if "libraries" in tables and postgres:
        # Library names are private to a user (migrations/007).
        connection.execute(text("ALTER TABLE libraries DROP CONSTRAINT IF EXISTS libraries_name_key"))
        connection.execute(text("DROP INDEX IF EXISTS ix_libraries_name"))
        connection.execute(text("CREATE INDEX ix_libraries_name ON libraries (name)"))
        _add_unique_constraint(connection, "libraries", "uq_libraries_user_name", "user_id, name")

    if "user_novel_follows" in tables:
        _add_missing_columns(connection, "user_novel_follows", {
            "download_policy": "VARCHAR(20) NOT NULL DEFAULT 'none'",
            "download_count": "INTEGER NOT NULL DEFAULT 0",
            "notification_policy": "VARCHAR(20) NOT NULL DEFAULT 'immediate'",
            "notification_count": "INTEGER NOT NULL DEFAULT 1",
        })

    if "novel_update_events" in tables:
        _add_missing_columns(connection, "novel_update_events", {
            "notification_visible": f"BOOLEAN NOT NULL DEFAULT {true}",
        })

    if "chapter_download_jobs" in tables:
        _add_missing_columns(connection, "chapter_download_jobs", {
            "max_attempts": "INTEGER NOT NULL DEFAULT 3",
            "next_attempt_at": "TIMESTAMP NULL",
            "started_at": "TIMESTAMP NULL",
            "finished_at": "TIMESTAMP NULL",
            "last_attempt_at": "TIMESTAMP NULL",
            "cancelled_at": "TIMESTAMP NULL",
            "cancellation_reason": "TEXT NULL",
            "error_code": "VARCHAR(80) NULL",
        })

    if "chapter_audio_jobs" in tables:
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_audio_jobs_queue ON chapter_audio_jobs (status, next_attempt_at, created_at)"
        ))
