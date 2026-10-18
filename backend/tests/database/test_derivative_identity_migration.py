"""Additive derivative identity binding preserves old recordings and uncertain data."""
from datetime import datetime
import os
from uuid import uuid4

from alembic import command
import pytest
from sqlalchemy import MetaData, create_engine, text

from app.db_migrations import alembic_config


@pytest.mark.parametrize('dialect', ['sqlite', 'postgresql'])
def test_0053_preserves_original_audio_and_marks_migration_identity_inferred(tmp_path, dialect):
    admin = None
    schema = None
    if dialect == 'postgresql':
        url = os.getenv('NEXUS_TEST_POSTGRES_URL')
        if not url:
            pytest.skip('Requires an owned disposable PostgreSQL database')
        schema = 'derivative_identity_' + uuid4().hex
        admin = create_engine(url)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    else:
        engine = create_engine(f'sqlite:///{tmp_path / "derivative-identity.db"}')
    try:
        with engine.begin() as connection:
            command.upgrade(alembic_config(connection), '0052')
        tables = MetaData()
        tables.reflect(engine)
        stamp = datetime(2020, 1, 2, 3, 4, 5)
        with engine.begin() as connection:
            def add(table_name, **values):
                return connection.execute(tables.tables[table_name].insert().values(**values)).inserted_primary_key[0]
            owner = add('users', username='audio-owner', password='unused', storage_id=str(uuid4()))
            other = add('users', username='other-audio-owner', password='unused', storage_id=str(uuid4()))
            library = add('libraries', user_id=owner, name='Original library', identity_key=str(uuid4()))
            novel = add('novels', library_id=library, title='Original story')
            chapter = add('chapters', novel_id=novel, chapter_number=-2, title='Current title is not the original recording title',
                          content_status='PRESENT', audio_status='PRESENT', retry_count=0)
            values = dict(library_id=library, novel_id=novel, chapter_id=chapter, status='completed', provider_id='fixture',
                          provider_url='http://synthetic.invalid/v1', provider_model='synthetic-only', provider_voice='fixture',
                          source_version='a' * 64, audio_path='/synthetic/completed.wav', audio_bytes=42,
                          created_at=stamp, updated_at=stamp, total_parts=1, completed_parts=1)
            known = add('chapter_audio_jobs', user_id=owner, **values)
            uncertain = add('chapter_audio_jobs', user_id=other, **values)
            part = add('chapter_audio_parts', job_id=known, part_index=0, text='Retained original narration.', status='completed')
            provider = add('reader_providers', user_id=owner, name='Original translator', kind='local',
                           base_url='http://synthetic.invalid/v1', model='synthetic')
            translation = dict(novel_id=novel, chapter_id=chapter, provider_id=provider, language='de',
                               source_version='b' * 64, provider_snapshot={'model': 'original-model'},
                               source_blocks=[{'id': 'original-block', 'text': 'Original words'}],
                               translated_blocks=[{'id': 'original-block', 'text': 'Original translation'}],
                               glossary={'Name': 'Original Name'}, status='completed', created_at=stamp, updated_at=stamp)
            known_translation = add('translation_jobs', user_id=owner, fingerprint='c' * 64, **translation)
            uncertain_translation = add('translation_jobs', user_id=other, fingerprint='d' * 64, **translation)
            old_download = add('chapter_download_jobs', user_id=owner, library_id=library, novel_id=novel,
                               chapter_id=chapter, status='queued', created_at=stamp, updated_at=stamp)
        with engine.begin() as connection:
            command.upgrade(alembic_config(connection), '0053')
            rows = list(connection.execute(text('SELECT * FROM chapter_audio_jobs ORDER BY id')).mappings())
            assert len(rows) == 2
            for row in rows:
                assert row['identity_inferred']
                assert row['chapter_title_snapshot'] is None and row['chapter_number_snapshot'] is None
                assert row['source_version'] == 'a' * 64 and row['audio_path'] == '/synthetic/completed.wav'
                assert row['audio_bytes'] == 42 and row['status'] == 'completed'
                assert str(row['created_at']).startswith('2020-01-02 03:04:05')
                assert str(row['updated_at']).startswith('2020-01-02 03:04:05')
            binding = connection.execute(text('SELECT c.chapter_key,s.manifest_epoch,s.revision FROM chapters c JOIN chapter_manifest_states s ON s.novel_id=c.novel_id WHERE c.id=:id'), {'id': chapter}).mappings().one()
            assert (rows[0]['chapter_key'], rows[0]['manifest_epoch'], rows[0]['manifest_revision']) == (binding['chapter_key'], binding['manifest_epoch'], str(binding['revision']))
            assert rows[1]['chapter_key'] is None and rows[1]['manifest_epoch'] is None and rows[1]['manifest_revision'] is None
            translated = list(connection.execute(text('SELECT * FROM translation_jobs ORDER BY id')).mappings())
            assert [row['id'] for row in translated] == [known_translation, uncertain_translation]
            assert all(row['identity_inferred'] for row in translated)
            assert all(row['chapter_title_snapshot'] is None and row['chapter_number_snapshot'] is None for row in translated)
            assert (translated[0]['chapter_key'], translated[0]['manifest_epoch'], translated[0]['manifest_revision']) == (binding['chapter_key'], binding['manifest_epoch'], str(binding['revision']))
            assert translated[1]['chapter_key'] is None and translated[1]['manifest_epoch'] is None
            assert all(row['source_version'] == 'b' * 64 and row['status'] == 'completed' for row in translated)
            download = connection.execute(text('SELECT chapter_identity,status FROM chapter_download_jobs WHERE id=:id'), {'id': old_download}).one()
            assert download.chapter_identity is None and download.status == 'queued'
            assert connection.execute(text('SELECT text FROM chapter_audio_parts WHERE id=:id'), {'id': part}).scalar_one() == 'Retained original narration.'
            assert connection.execute(text('SELECT source_version FROM translation_jobs WHERE id=:id'), {'id': known_translation}).scalar_one() == 'b' * 64
            # New rows must have a real false server default on both dialects.
            connection.execute(text('INSERT INTO chapter_audio_jobs(user_id,library_id,novel_id,chapter_id,status,provider_id,provider_url,provider_model,provider_voice) VALUES(:u,:l,:n,:c,\'completed\',\'fixture\',\'http://synthetic.invalid/v1\',\'synthetic\',\'fixture\')'), {'u': owner, 'l': library, 'n': novel, 'c': chapter})
            inferred = connection.execute(text('SELECT identity_inferred FROM chapter_audio_jobs WHERE id > :id'), {'id': uncertain}).scalar_one()
            assert inferred in (False, 0) and not isinstance(inferred, str)
        with engine.begin() as connection:
            command.downgrade(alembic_config(connection), '0052')
            assert connection.execute(text('SELECT status FROM chapter_download_jobs WHERE id=:id'), {'id': old_download}).scalar_one() == 'queued'
            assert connection.execute(text('SELECT source_version FROM chapter_audio_jobs WHERE id=:id'), {'id': known}).scalar_one() == 'a' * 64
            assert connection.execute(text('SELECT text FROM chapter_audio_parts WHERE id=:id'), {'id': part}).scalar_one() == 'Retained original narration.'
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            admin.dispose()
