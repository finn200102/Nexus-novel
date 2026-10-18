"""Additive private artifacts preserve old installs in both supported databases."""
# ruff: noqa: F811
from uuid import uuid4
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text, inspect
from app.db_migrations import alembic_config
from config.database import Base
from tests.database.test_reading_run_migration import run_engine  # noqa: F401


def test_0050_is_additive_and_reversible(run_engine):
    with run_engine.connect() as connection:
        command.upgrade(alembic_config(connection), '0049')
        connection.execute(text("INSERT INTO users(username,password,storage_id) VALUES('private-guide-legacy','unused',:identity)"), {'identity': str(uuid4())})
        connection.commit()
        command.upgrade(alembic_config(connection), '0050')
        connection.commit()
        assert {'private_guide_jobs','private_guide_artifacts','private_guide_operations'}.issubset(inspect(connection).get_table_names())
        assert connection.execute(text('SELECT username FROM users')).scalar_one() == 'private-guide-legacy'
        assert not connection.execute(text('SELECT id FROM private_guide_jobs')).all()
        command.downgrade(alembic_config(connection), '0049')
        connection.commit()
        assert 'private_guide_jobs' not in inspect(connection).get_table_names()
        assert connection.execute(text('SELECT username FROM users')).scalar_one() == 'private-guide-legacy'


def test_head_matches_current_models(run_engine):
    with run_engine.connect() as connection:
        command.upgrade(alembic_config(connection), 'head')
        connection.commit()
        assert compare_metadata(MigrationContext.configure(connection, opts={'compare_type': True}), Base.metadata) == []
