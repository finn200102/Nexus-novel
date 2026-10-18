"""Additive migration and retained account audit across story deletion."""
import os
from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import create_engine, MetaData, Table, text, inspect
from app.db_migrations import alembic_config


@pytest.mark.parametrize('dialect',['sqlite','postgresql'])
def test_source_migration_upgrade_retains_existing_data_and_audit_when_story_removed(tmp_path,dialect):
    admin=None
    if dialect=='postgresql':
        url=os.environ.get('NEXUS_TEST_POSTGRES_URL')
        if not url:pytest.skip('Requires uniquely owned disposable PostgreSQL')
        admin=create_engine(url);schema='source_migration_'+uuid4().hex
        with admin.begin() as connection:connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine=create_engine(url,connect_args={'options':f'-csearch_path={schema}'})
    else:engine=create_engine(f'sqlite:///{tmp_path / "source_migrations.db"}')
    try:
        with engine.connect() as connection:
            if dialect=='sqlite':connection.execute(text('PRAGMA foreign_keys=ON'))
            command.upgrade(alembic_config(connection),'0045');connection.commit()
            connection.execute(text("INSERT INTO users (id,username,password,storage_id) VALUES (1,'private-owner','unused','migration-owner')"))
            connection.execute(text("INSERT INTO libraries (id,user_id,name) VALUES (1,1,'Private')"))
            connection.execute(text("INSERT INTO novels (id,library_id,title) VALUES (1,1,'Original'),(2,1,'Replacement')"))
            connection.commit();command.upgrade(alembic_config(connection),'0046');connection.commit()
            metadata=MetaData()
            migrations=Table('source_migrations',metadata,autoload_with=connection)
            operations=Table('source_migration_operations',metadata,autoload_with=connection)
            connection.execute(migrations.insert().values(id=1,user_id=1,source_novel_id=1,target_novel_id=2,revision=1,status='applied',
                plan={'source':{'title':'Original'}},counts={},created_rows={},target_guard='guard'))
            connection.execute(operations.insert().values(user_id=1,migration_id=1,operation_id='lost-ack',fingerprint='exact',response={'id':1}))
            connection.execute(text('DELETE FROM novels WHERE id=1'));connection.commit()
            row=connection.execute(migrations.select()).mappings().one()
            assert row['source_novel_id'] is None and row['target_novel_id']==2
            assert connection.execute(operations.select()).mappings().one()['response']=={'id':1}
            assert connection.execute(text('SELECT title FROM novels WHERE id=2')).scalar()=='Replacement'
            command.downgrade(alembic_config(connection),'0045');connection.commit()
            assert 'source_migrations' not in inspect(connection).get_table_names()
            assert connection.execute(text('SELECT title FROM novels WHERE id=2')).scalar()=='Replacement'
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            admin.dispose()
