"""Alembic upgrade paths: empty database, pre-Alembic database, concurrency.

SQLite tests always run. The PostgreSQL tests run when NEXUS_TEST_POSTGRES_URL
points at a database the tests may wipe, for example:

    docker run -d --rm -p 127.0.0.1:55439:5432 -e POSTGRES_PASSWORD=pg postgres:17-alpine
    NEXUS_TEST_POSTGRES_URL=postgresql://postgres:pg@127.0.0.1:55439/postgres uv run pytest tests/database
"""

import os
import threading
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app import models  # noqa: F401
from app.db_migrations import alembic_config, upgrade_database
from config.database import Base

FIXTURES = Path(__file__).parent / "fixtures"
POSTGRES_URL = os.getenv("NEXUS_TEST_POSTGRES_URL")
requires_postgres = pytest.mark.skipif(not POSTGRES_URL, reason="NEXUS_TEST_POSTGRES_URL is not set")


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(engine) -> str | None:
    with engine.connect() as connection:
        return MigrationContext.configure(connection).get_current_revision()


def schema_drift(engine) -> list:
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        return compare_metadata(context, Base.metadata)


def column_names(engine, table: str) -> set[str]:
    return {column["name"] for column in inspect(engine).get_columns(table)}


@pytest.fixture
def sqlite_engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migrations.db'}")
    yield engine
    engine.dispose()


@pytest.fixture
def postgres_engine():
    engine = create_engine(POSTGRES_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    yield engine
    engine.dispose()


def test_single_head():
    assert len(ScriptDirectory.from_config(alembic_config()).get_heads()) == 1


@requires_postgres
@pytest.mark.parametrize("same_operation", [False, True])
def test_discovery_preferences_serialize_between_devices(postgres_engine, same_operation):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy.orm import sessionmaker
    from fastapi import HTTPException
    from app.models import User, ReaderPreference
    from app.schemas.discovery_preferences import DiscoveryPreferenceWrite
    from app.services.discovery_preferences import write
    upgrade_database(postgres_engine)
    factory = sessionmaker(bind=postgres_engine)
    with factory() as db:
        user = User(username="taste-owner", password="unused")
        db.add(user); db.commit(); user_id = user.id
    barrier = threading.Barrier(2)
    def device(index):
        with factory() as db:
            user = db.get(User, user_id)
            value = DiscoveryPreferenceWrite(expected_revision=0, operation_id="same" if same_operation else str(index), values={"tags": ["Slow burn"]})
            barrier.wait(timeout=10)
            try: return 200, write(db, user, value)
            except HTTPException as exc: db.rollback(); return exc.status_code, exc.detail
    with ThreadPoolExecutor(max_workers=2) as pool: results = list(pool.map(device, [1, 2]))
    assert sorted(code for code, _ in results) == ([200, 200] if same_operation else [200, 409])
    with factory() as db:
        row = db.query(ReaderPreference).filter_by(scope="discovery").one()
        assert row.revision == 1 and row.values["tags"] == ["Slow burn"]


@requires_postgres
def test_concurrent_demo_clicks_do_not_duplicate_stories(postgres_engine):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy.orm import sessionmaker
    from app.models import User, Library, Novel, Chapter
    from app.routers.onboarding import add_demo, DemoRequest
    upgrade_database(postgres_engine)
    factory = sessionmaker(bind=postgres_engine)
    with factory() as db:
        user = User(username="demo-owner", password="unused")
        db.add(user); db.flush()
        library = Library(name="Private", user_id=user.id)
        db.add(library); db.commit()
        user_id, library_id = user.id, library.id
    barrier = threading.Barrier(2)
    def click(_):
        with factory() as db:
            user = db.get(User, user_id)
            barrier.wait(timeout=10)
            return add_demo(DemoRequest(library_id=library_id), db, user)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(click, [1, 2]))
    assert sorted(sum(story.created for story in result.stories) for result in results) == [0, 2]
    with factory() as db:
        assert db.query(Novel).count() == 2 and db.query(Chapter).count() == 3


@requires_postgres
def test_concurrent_source_replacements_retain_every_original(postgres_engine):
    from concurrent.futures import ThreadPoolExecutor
    from sqlalchemy.orm import sessionmaker
    from app.models import User, Library, Novel, Chapter, ChapterVersion
    from app.services.chapter_document import from_text
    from app.services.chapter_services import update_chapter
    upgrade_database(postgres_engine)
    factory = sessionmaker(bind=postgres_engine)
    original = from_text("Original chapter")
    with factory() as db:
        user = User(username="revision-owner", password="unused")
        db.add(user); db.flush()
        library = Library(name="Private", user_id=user.id)
        db.add(library); db.flush()
        novel = Novel(title="Versioned", library_id=library.id, url="nexus-local:concurrency")
        db.add(novel); db.flush()
        chapter = Chapter(novel_id=novel.id, chapter_number=1, content=original["plain_text"], document=original)
        db.add(chapter); db.commit()
        chapter_id = chapter.id
    barrier = threading.Barrier(2)
    def source(index):
        with factory() as db:
            barrier.wait(timeout=10)
            return update_chapter(db, chapter_id, {"content": f"Revised chapter {index}"}).document["content_version"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        replacements = list(pool.map(source, [1, 2]))
    with factory() as db:
        current = db.get(Chapter, chapter_id)
        versions = db.query(ChapterVersion).filter_by(chapter_id=chapter_id).all()
        assert len(versions) == 2
        assert {version.content_version for version in versions} | {current.document["content_version"]} == {original["content_version"], *replacements}


@requires_postgres
@pytest.mark.parametrize("same_operation", [False, True])
def test_reader_preference_writes_serialize_between_devices(postgres_engine, same_operation):
    from concurrent.futures import ThreadPoolExecutor
    from fastapi import HTTPException
    from sqlalchemy.orm import sessionmaker
    from app.models.user import User
    from app.models.reader_preference import ReaderPreference
    from app.routers.reader_preferences import write
    from app.schemas.reader_preferences import PreferenceWrite
    upgrade_database(postgres_engine)
    factory = sessionmaker(bind=postgres_engine)
    with factory() as db:
        user = User(username="two-device-test", password="unused")
        db.add(user)
        db.commit()
        user_id = user.id
    barrier = threading.Barrier(2)
    def device(index):
        with factory() as db:
            user = db.get(User, user_id)
            value = PreferenceWrite(expected_revision=0, operation_id="same" if same_operation else f"device-{index}", values={"typography": {"fontSize": 22}})
            barrier.wait(timeout=10)
            try:
                return 200, write(db, user, value)
            except HTTPException as exc:
                db.rollback()
                return exc.status_code, exc.detail
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(device, [1, 2]))
    assert sorted(code for code, _ in results) == ([200, 200] if same_operation else [200, 409])
    with factory() as db:
        row = db.query(ReaderPreference).one()
        assert row.revision == 1 and row.values == {"typography": {"fontSize": 22}}


def test_empty_sqlite_database_upgrades_to_models(sqlite_engine):
    upgrade_database(sqlite_engine)

    assert current_revision(sqlite_engine) == head_revision()
    assert schema_drift(sqlite_engine) == []


# An old SQLite install: tables as early versions created them, before the
# runtime ALTERs and before several tables existed.
LEGACY_SQLITE_SCHEMA = [
    "CREATE TABLE users (id INTEGER PRIMARY KEY, created_at TIMESTAMP, updated_at TIMESTAMP,"
    " username VARCHAR(100) NOT NULL, password VARCHAR(255) NOT NULL)",
    "CREATE TABLE libraries (id INTEGER PRIMARY KEY, created_at TIMESTAMP, updated_at TIMESTAMP,"
    " name VARCHAR(100) NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id))",
    "CREATE TABLE novels (id INTEGER PRIMARY KEY, created_at TIMESTAMP, updated_at TIMESTAMP,"
    " title VARCHAR(255) NOT NULL, url VARCHAR(255), library_id INTEGER NOT NULL REFERENCES libraries(id),"
    " follow_state VARCHAR(20))",
    "CREATE TABLE chapters (id INTEGER PRIMARY KEY, created_at TIMESTAMP, updated_at TIMESTAMP,"
    " title VARCHAR(255), content TEXT, chapter_number INTEGER NOT NULL, novel_id INTEGER REFERENCES novels(id),"
    " site_chapter_id BIGINT, content_status VARCHAR(10) NOT NULL, audio_status VARCHAR(10) NOT NULL)",
    "INSERT INTO users (id, username, password) VALUES (1, 'first', 'x'), (2, 'second', 'y')",
    "INSERT INTO libraries (id, name, user_id) VALUES (1, 'Library', 1)",
    "INSERT INTO novels (id, title, url, library_id, follow_state) VALUES (1, 'Kept', 'https://example.test/1', 1, 'muted')",
]


def test_pre_alembic_sqlite_database_is_upgraded_once(sqlite_engine):
    with sqlite_engine.begin() as connection:
        for statement in LEGACY_SQLITE_SCHEMA:
            connection.execute(text(statement))

    upgrade_database(sqlite_engine)

    assert current_revision(sqlite_engine) == head_revision()
    assert {"is_admin", "is_disabled"} <= column_names(sqlite_engine, "users")
    assert {"metadata_id", "scrape_status", "followed_at"} <= column_names(sqlite_engine, "novels")
    # The upgraded installation must be readable by today's application, not
    # merely stamped at head with old nullable source columns still missing.
    from app.models import Novel
    from sqlalchemy.orm import Session
    with Session(sqlite_engine) as db:
        kept=db.get(Novel,1)
        assert kept.title=='Kept' and kept.site is None and kept.site_story_id is None
    assert {"retry_count", "download_error"} <= column_names(sqlite_engine, "chapters")
    assert set(Base.metadata.tables) <= set(inspect(sqlite_engine).get_table_names())
    with sqlite_engine.connect() as connection:
        assert connection.execute(text("SELECT title, follow_state FROM novels")).all() == [("Kept", "on_hold")]
        admins = connection.execute(text("SELECT username FROM users WHERE is_admin")).scalars().all()
    # The upgrade keeps the instance administrable: the first user becomes
    # admin, once.
    assert admins == ["first"]

    with sqlite_engine.begin() as connection:
        connection.execute(text("UPDATE users SET is_admin = 0 WHERE username = 'first'"))
        connection.execute(text("UPDATE users SET is_admin = 1 WHERE username = 'second'"))
    upgrade_database(sqlite_engine)
    with sqlite_engine.connect() as connection:
        admins = connection.execute(text("SELECT username FROM users WHERE is_admin")).scalars().all()
    assert admins == ["second"]


@requires_postgres
def test_empty_postgres_database_upgrades_to_models(postgres_engine):
    upgrade_database(postgres_engine)

    assert current_revision(postgres_engine) == head_revision()
    assert schema_drift(postgres_engine) == []


def _load_legacy_postgres(engine) -> None:
    raw = engine.raw_connection()
    try:
        with raw.cursor() as cursor:
            cursor.execute((FIXTURES / "pre_alembic_postgres.sql").read_text())
        raw.commit()
    finally:
        raw.close()


@requires_postgres
def test_pre_alembic_postgres_database_upgrades_without_drift(postgres_engine):
    _load_legacy_postgres(postgres_engine)
    with postgres_engine.begin() as connection:
        connection.execute(text("INSERT INTO users (id, username, password, is_admin) VALUES (1, 'owner', 'x', true)"))

    upgrade_database(postgres_engine)

    assert current_revision(postgres_engine) == head_revision()
    assert schema_drift(postgres_engine) == []


@requires_postgres
def test_older_postgres_install_is_brought_to_the_baseline(postgres_engine):
    """An install from before several runtime ALTERs and hand-run SQL files."""
    _load_legacy_postgres(postgres_engine)
    with postgres_engine.begin() as connection:
        for statement in [
            "DROP TABLE saved_searches",
            "DROP TABLE reading_history",
            "DROP INDEX ix_audio_jobs_queue",
            "ALTER TABLE users DROP COLUMN is_admin",
            "ALTER TABLE novels DROP COLUMN follow_state",
            "ALTER TABLE novels DROP COLUMN scrape_status",
            "ALTER TABLE novels ALTER COLUMN story_id TYPE INTEGER",
            "ALTER TABLE chapters DROP COLUMN retry_count",
            "ALTER TABLE user_novel_follows DROP COLUMN notification_count",
            "ALTER TABLE libraries DROP CONSTRAINT uq_libraries_user_name",
            "ALTER TABLE libraries ADD CONSTRAINT libraries_name_key UNIQUE (name)",
            "ALTER TABLE novels DROP CONSTRAINT uq_novels_library_url",
            # Older start-up code created this as a plain unique index.
            "CREATE UNIQUE INDEX uq_novels_library_url ON novels (library_id, url)",
            "ALTER TABLE novels ADD CONSTRAINT novels_metadata_id_key UNIQUE (metadata_id)",
            "INSERT INTO users (id, username, password) VALUES (1, 'owner', 'x'), (2, 'guest', 'y')",
        ]:
            connection.execute(text(statement))

    upgrade_database(postgres_engine)

    assert schema_drift(postgres_engine) == []
    with postgres_engine.connect() as connection:
        admins = connection.execute(text("SELECT username FROM users WHERE is_admin")).scalars().all()
    assert admins == ["owner"]


@requires_postgres
def test_concurrent_starts_migrate_once(postgres_engine):
    errors = []

    def start():
        engine = create_engine(POSTGRES_URL)
        try:
            upgrade_database(engine)
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)
        finally:
            engine.dispose()

    threads = [threading.Thread(target=start) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert current_revision(postgres_engine) == head_revision()
    assert schema_drift(postgres_engine) == []


def test_stamped_legacy_database_missing_nullable_source_fact_reaches_readable_head(sqlite_engine):
    with sqlite_engine.connect() as connection:
        command.upgrade(alembic_config(connection),'0051');connection.commit()
        connection.execute(text('ALTER TABLE novels DROP COLUMN site'));connection.commit()
    upgrade_database(sqlite_engine)
    assert current_revision(sqlite_engine)==head_revision()
    assert 'site' in column_names(sqlite_engine,'novels')


def test_case_colliding_usernames_block_the_unique_username_migration(sqlite_engine):
    with sqlite_engine.begin() as connection:
        command.upgrade(alembic_config(connection), "0009")
        connection.execute(text("INSERT INTO users (username, password) VALUES ('Reader', 'x'), ('reader', 'y'), ('solo', 'z')"))

    with pytest.raises(RuntimeError) as excinfo:
        upgrade_database(sqlite_engine)

    message = str(excinfo.value)
    assert "'Reader' / 'reader'" in message
    assert "solo" not in message
    assert current_revision(sqlite_engine) == "0009"

    with sqlite_engine.begin() as connection:
        connection.execute(text("DELETE FROM users WHERE username = 'Reader'"))
    upgrade_database(sqlite_engine)
    assert current_revision(sqlite_engine) == head_revision()
