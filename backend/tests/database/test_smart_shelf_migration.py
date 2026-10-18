"""Preserve old libraries and assign stable rule-reference identities."""
import os
from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import create_engine, text, inspect
from app.db_migrations import alembic_config


@pytest.mark.parametrize('dialect', ['sqlite', 'postgresql'])
def test_additive_smart_shelf_migration_preserves_parents_and_downgrades(tmp_path, dialect):
    admin = None
    if dialect == 'postgresql':
        url = os.environ.get('NEXUS_TEST_POSTGRES_URL')
        if not url:
            pytest.skip('Requires the owned disposable PostgreSQL')
        admin = create_engine(url)
        schema = 'smart_migration_' + uuid4().hex
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    else:
        engine = create_engine(f'sqlite:///{tmp_path / "smart_migration.db"}')
    try:
        with engine.connect() as connection:
            if dialect == 'sqlite':
                connection.execute(text('PRAGMA foreign_keys=ON'))
            command.upgrade(alembic_config(connection), '0046')
            connection.commit()
            connection.execute(text("INSERT INTO users (id,username,password,storage_id) VALUES (1,'owner','unused','smart-owner')"))
            connection.execute(text("INSERT INTO libraries (id,user_id,name) VALUES (1,1,'Original library')"))
            connection.execute(text("INSERT INTO shelves (id,user_id,name,position) VALUES (1,1,'Original shelf',0)"))
            connection.execute(text("INSERT INTO novels (id,library_id,title) VALUES (1,1,'Original story')"))
            connection.execute(text("INSERT INTO shelf_novels (id,shelf_id,novel_id,position) VALUES (1,1,1,0)"))
            connection.commit()
            command.upgrade(alembic_config(connection), '0047')
            connection.commit()
            identity = connection.execute(text('SELECT identity_key FROM libraries WHERE id=1')).scalar_one()
            shelf_identity = connection.execute(text('SELECT identity_key FROM shelves WHERE id=1')).scalar_one()
            assert identity and shelf_identity and identity != shelf_identity
            assert connection.execute(text('SELECT count(*) FROM shelf_novels')).scalar_one() == 1
            command.upgrade(alembic_config(connection), '0047')
            assert connection.execute(text('SELECT identity_key FROM libraries WHERE id=1')).scalar_one() == identity
            connection.commit()
            command.downgrade(alembic_config(connection), '0046')
            connection.commit()
            assert 'smart_shelves' not in inspect(connection).get_table_names()
            assert 'identity_key' not in {column['name'] for column in inspect(connection).get_columns('libraries')}
            assert connection.execute(text('SELECT name FROM libraries WHERE id=1')).scalar_one() == 'Original library'
            assert connection.execute(text('SELECT count(*) FROM shelf_novels')).scalar_one() == 1
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            admin.dispose()
