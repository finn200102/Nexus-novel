import os
from uuid import uuid4
import pytest
from alembic import command
from sqlalchemy import create_engine, text, inspect, MetaData, Table
from app.db_migrations import alembic_config


@pytest.mark.parametrize('dialect', ['sqlite', 'postgresql'])
def test_0044_preserves_aggregate_and_backfills_only_unknown_reservations(tmp_path, dialect):
    admin = None
    if dialect == 'postgresql':
        url = os.environ.get('NEXUS_TEST_POSTGRES_URL')
        if not url:
            pytest.skip('An owned disposable PostgreSQL URL is required')
        admin = create_engine(url)
        schema = 'ledger_migration_' + uuid4().hex
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    else:
        engine = create_engine(f'sqlite:///{tmp_path / "ledger.db"}')
    try:
        with engine.connect() as connection:
            command.upgrade(alembic_config(connection), '0043'); connection.commit()
            connection.execute(text("INSERT INTO users (id,username,password,storage_id) VALUES (1,'owner','unused','migration-owner')"))
            for number, reserved in [(1, 77), (2, 0)]:
                connection.execute(text("INSERT INTO reader_providers (id,user_id,name,kind,base_url,model,used_microusd,reserved_microusd,budget_microusd) VALUES (:id,1,'Fixture','openai_compatible','https://unused','unknown-old-model',123,:reserved,1000)"), {'id':number,'reserved':reserved})
            connection.execute(text("INSERT INTO libraries (id,user_id,name) VALUES (1,1,'Fixture')"))
            connection.execute(text("INSERT INTO novels (id,library_id,title) VALUES (1,1,'Fixture')"))
            connection.execute(text("INSERT INTO chapters (id,novel_id,chapter_number,content_status,audio_status,retry_count) VALUES (1,1,1,'PRESENT','MISSING',0)"))
            jobs = Table('translation_jobs', MetaData(), autoload_with=connection)
            for index, (provider_id, status) in enumerate([(1,'processing'),(2,'retry_wait'),(1,'queued'),(1,'completed')], 1):
                connection.execute(jobs.insert().values(id=index, user_id=1, novel_id=1, chapter_id=1, provider_id=provider_id,
                    language='de', fingerprint=str(index)*64, source_version='a'*64, provider_snapshot={'model':'fixture'},
                    source_blocks=[{'id':'original','text':'Source'}], glossary={}, translated_blocks=[{'id':'done','text':'Saved'}],
                    status=status, lease_owner='previous-worker', input_tokens=5, output_tokens=7, charged_microusd=19))
            connection.commit()
            command.upgrade(alembic_config(connection), '0044'); connection.commit()
            rows = connection.execute(text('SELECT provider_id,status,reserved_microusd,actual_microusd,input_tokens,output_tokens,expires_at FROM reader_provider_requests')).all()
            assert rows == [(1, 'legacy_unknown', 77, None, None, None, None)]
            assert connection.execute(text('SELECT used_microusd,reserved_microusd FROM reader_providers ORDER BY id')).all() == [(123,77),(123,0)]
            assert connection.execute(text('SELECT status FROM translation_jobs ORDER BY id')).scalars().all() == ['failed','failed','queued','completed']
            paused = connection.execute(text("SELECT error_code,lease_owner,input_tokens,output_tokens,charged_microusd FROM translation_jobs WHERE id IN (1,2) ORDER BY id")).all()
            assert paused == [('LEGACY_PAID_REVIEW_REQUIRED',None,5,7,19)] * 2
            assert connection.execute(text('SELECT translated_blocks FROM translation_jobs WHERE id=1')).scalar() is not None
            command.downgrade(alembic_config(connection), '0043'); connection.commit()
            assert 'reader_provider_requests' not in inspect(connection).get_table_names()
            assert connection.execute(text('SELECT used_microusd,reserved_microusd FROM reader_providers ORDER BY id')).all() == [(123,77),(123,0)]
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            admin.dispose()
