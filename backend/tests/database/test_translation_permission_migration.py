import os
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from app.db_migrations import alembic_config


@pytest.mark.parametrize('dialect',['sqlite','postgresql'])
def test_0042_preserves_permission_choices_and_downgrades_unset_to_denial(tmp_path,dialect):
    admin=None
    schema=None
    if dialect=='postgresql':
        url=os.environ.get('NEXUS_TEST_POSTGRES_URL')
        if not url:pytest.skip('Set NEXUS_TEST_POSTGRES_URL to an owned disposable PostgreSQL database')
        admin=create_engine(url);schema='permission_migration_'+uuid4().hex
        with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
    else:engine=create_engine(f'sqlite:///{tmp_path / "permission-migration.db"}')
    try:
        with engine.connect() as connection:
            command.upgrade(alembic_config(connection),'0041');connection.commit()
        # Use historical wire columns throughout: current ORM models include
        # later guide/image fields absent from both schemas under test.
        with engine.begin() as connection:
            user_id=connection.execute(text("INSERT INTO users(username,password,storage_id) VALUES('migration-owner','unused',:storage) RETURNING id"),
                {'storage':uuid4().hex}).scalar_one()
            library_id=connection.execute(text("INSERT INTO libraries(user_id,name) VALUES(:user,'Private') RETURNING id"),{'user':user_id}).scalar_one()
            provider_id=connection.execute(text("INSERT INTO reader_providers(user_id,name,kind,base_url,model) VALUES(:user,'Local','local','http://unused','fixture') RETURNING id"),{'user':user_id}).scalar_one()
            for number,choice in enumerate([True,False,'default']):
                novel_id=connection.execute(text('INSERT INTO novels(library_id,title) VALUES(:library,:title) RETURNING id'),
                    {'library':library_id,'title':f'Story {number}'}).scalar_one()
                values={'user':user_id,'novel':novel_id,'provider':provider_id}
                if choice=='default':
                    connection.execute(text('INSERT INTO story_processing_permissions(user_id,novel_id,provider_id,translation,ao3_consent) VALUES(:user,:novel,:provider,true,true)'),values)
                else:
                    connection.execute(text('INSERT INTO story_processing_permissions(user_id,novel_id,provider_id,translation,companion,ao3_consent) VALUES(:user,:novel,:provider,true,:choice,true)'),{**values,'choice':choice})
        with engine.connect() as connection:
            command.upgrade(alembic_config(connection),'0042');connection.commit()
        columns={column['name']:column for column in inspect(engine).get_columns('story_processing_permissions')}
        assert columns['companion']['nullable'] is True and columns['companion']['default'] is not None
        with engine.begin() as connection:
            rows=connection.execute(text('SELECT companion,translation,ao3_consent FROM story_processing_permissions ORDER BY id')).all()
            assert [row.companion for row in rows]==[True,False,False]
            assert all(row.translation and row.ao3_consent for row in rows)
            novel_id=connection.execute(text("INSERT INTO novels(library_id,title) VALUES(:library,'Previously unset') RETURNING id"),{'library':library_id}).scalar_one()
            connection.execute(text('INSERT INTO story_processing_permissions(user_id,novel_id,provider_id,translation,companion) VALUES(:user,:novel,:provider,true,NULL)'),
                {'user':user_id,'novel':novel_id,'provider':provider_id})
            assert connection.execute(text('SELECT companion FROM story_processing_permissions ORDER BY id DESC LIMIT 1')).scalar_one() is None
        with engine.connect() as connection:
            command.downgrade(alembic_config(connection),'0041');connection.commit()
        columns={column['name']:column for column in inspect(engine).get_columns('story_processing_permissions')}
        assert columns['companion']['nullable'] is False
        with engine.connect() as connection:
            assert list(connection.execute(text('SELECT companion FROM story_processing_permissions ORDER BY id')).scalars())==[True,False,False,False]
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            admin.dispose()
