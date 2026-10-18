"""Old text grants and accounting survive 0051; images remain explicitly off."""
import os
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, text, inspect
from app.db_migrations import alembic_config


@pytest.mark.parametrize('dialect', ['sqlite', 'postgresql'])
def test_0051_is_additive_and_never_promotes_existing_text_grants(tmp_path, dialect):
    admin = None
    if dialect == 'postgresql':
        url = os.getenv('NEXUS_TEST_POSTGRES_URL')
        if not url: pytest.skip('Owned disposable PostgreSQL required')
        admin = create_engine(url); schema = 'guide_provider_' + uuid4().hex
        with admin.begin() as connection: connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    else: engine = create_engine(f'sqlite:///{tmp_path / "guide-provider.db"}')
    try:
        with engine.connect() as connection:
            command.upgrade(alembic_config(connection), '0050'); connection.commit()
            connection.execute(text("INSERT INTO users(id,username,password,storage_id) VALUES(1,'owner','unused','guide-migration-owner')"))
            connection.execute(text("INSERT INTO libraries(id,user_id,name) VALUES(1,1,'Private')"))
            connection.execute(text("INSERT INTO novels(id,library_id,title) VALUES(1,1,'Private')"))
            connection.execute(text("INSERT INTO reader_providers(id,user_id,name,kind,base_url,model,input_price,output_price,budget_microusd,used_microusd,reserved_microusd) VALUES(1,1,'Old','anthropic','https://unused.invalid','old-model',1,2,1000,123,77)"))
            connection.execute(text("INSERT INTO story_processing_permissions(user_id,novel_id,provider_id,translation,companion,ao3_consent) VALUES(1,1,1,true,true,true)"))
            connection.commit()
            command.upgrade(alembic_config(connection), '0051'); connection.commit()
            assert connection.execute(text('SELECT capabilities,image_model,image_price_microusd,used_microusd,reserved_microusd FROM reader_providers')).one() == (None,None,0,123,77)
            assert connection.execute(text('SELECT portrait,portrait_ao3_consent,portrait_provider_snapshot,translation,companion,ao3_consent FROM story_processing_permissions')).one() == (False,False,None,True,True,True)
            assert {'purpose','job_key','item_key'} <= {row['name'] for row in inspect(connection).get_columns('reader_provider_requests')}
            assert any(index['name']=='uq_provider_work_dispatch' and index['unique'] for index in inspect(connection).get_indexes('reader_provider_requests'))
            assert next(row for row in inspect(connection).get_columns('story_processing_permissions') if row['name'] == 'translation')['nullable']
            connection.execute(text('UPDATE story_processing_permissions SET translation=NULL'))
            connection.commit()
            command.downgrade(alembic_config(connection), '0050'); connection.commit()
            assert 'portrait' not in {row['name'] for row in inspect(connection).get_columns('story_processing_permissions')}
            assert connection.execute(text('SELECT translation,companion FROM story_processing_permissions')).one() == (False,True)
            assert connection.execute(text('SELECT used_microusd,reserved_microusd FROM reader_providers')).one() == (123,77)
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection: connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            admin.dispose()
