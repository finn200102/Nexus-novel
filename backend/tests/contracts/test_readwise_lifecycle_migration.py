"""0058 preserves notes and creates immutable raw-SQL insertion lifecycles."""
import importlib.util
from pathlib import Path
import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_migration_backfill_replacement_and_reversible_schema(tmp_path):
    engine=sa.create_engine(f'sqlite:///{tmp_path/"export-migration.db"}')
    path=Path(__file__).resolve().parents[2]/'alembic/versions/0058_export_lifecycles.py'
    spec=importlib.util.spec_from_file_location('export_migration',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE reading_annotations(id INTEGER PRIMARY KEY, quote TEXT)')
        connection.exec_driver_sql('CREATE TABLE readwise_connections(id INTEGER PRIMARY KEY, token_encrypted TEXT)')
        connection.exec_driver_sql("INSERT INTO reading_annotations VALUES(1,'retained quote')")
        connection.exec_driver_sql("INSERT INTO readwise_connections VALUES(1,'retained encrypted token')")
        module.op=Operations(MigrationContext.configure(connection));module.upgrade()
        old=connection.exec_driver_sql('SELECT export_key FROM reading_annotations').scalar_one()
        assert len(old)==32
        assert connection.exec_driver_sql('SELECT quote FROM reading_annotations').scalar_one()=='retained quote'
        connection.exec_driver_sql('DELETE FROM reading_annotations WHERE id=1')
        connection.exec_driver_sql("INSERT INTO reading_annotations(id,quote) VALUES(1,'retained quote')")
        new=connection.exec_driver_sql('SELECT export_key FROM reading_annotations').scalar_one()
        assert new!=old
        with pytest.raises(sa.exc.IntegrityError,match='immutable export lifecycle'):
            connection.exec_driver_sql("UPDATE reading_annotations SET export_key='forged' WHERE id=1")
        module.downgrade()
        assert 'export_key' not in {c['name'] for c in sa.inspect(connection).get_columns('reading_annotations')}
        assert connection.exec_driver_sql('SELECT quote FROM reading_annotations').scalar_one()=='retained quote'
