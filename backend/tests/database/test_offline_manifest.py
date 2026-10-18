import os
from uuid import uuid4
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.db_migrations import upgrade_database
from app.models import User, Library, Novel, Chapter
from app.models.chapter import ContentStatus
from app.models.translation import ReaderProvider, TranslationJob
from app.services.chapter_document import from_html
from app.services.offline_library_service import manifest, translation_content


@pytest.fixture(params=['sqlite', 'postgresql'])
def offline_engine(request, tmp_path):
    admin = None
    if request.param == 'postgresql':
        url = os.getenv('NEXUS_TEST_POSTGRES_URL')
        if not url:
            pytest.skip('An owned disposable PostgreSQL URL is required')
        admin = create_engine(url); schema = 'offline_manifest_' + uuid4().hex
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA {schema}'))
        engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    else:
        engine = create_engine(f'sqlite:///{tmp_path / "offline.db"}')
    try:
        upgrade_database(engine)
        yield engine
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA {schema} CASCADE'))
            admin.dispose()


def test_windowed_latest_language_variants_are_current_bounded_and_paginated(offline_engine):
    with sessionmaker(bind=offline_engine)() as db:
        user = User(username='offline-sql-owner', password='unused'); db.add(user); db.flush()
        library = Library(user_id=user.id, name='Private'); db.add(library); db.flush()
        novel = Novel(library_id=library.id, title='Bounded private variants'); db.add(novel); db.flush()
        document = from_html('<p>Original one.</p>'); other = from_html('<p>Original two.</p>')
        first = Chapter(novel_id=novel.id, chapter_number=3, content=document['plain_text'], document=document, content_status=ContentStatus.PRESENT)
        second = Chapter(novel_id=novel.id, chapter_number=7, content=other['plain_text'], document=other, content_status=ContentStatus.PRESENT)
        provider = ReaderProvider(user_id=user.id, name='Fixture', kind='local', base_url='http://unused', model='fixture')
        db.add_all([first, second, provider]); db.flush()
        db.refresh(first)
        from app.services.chapter_identity_service import identity
        captured=identity(first)
        def variant(language, version):
            row = TranslationJob(user_id=user.id, novel_id=novel.id, chapter_id=first.id, provider_id=provider.id,
                language=language, source_version=version, fingerprint=uuid4().hex, provider_snapshot={}, glossary={},
                source_blocks=document['blocks'], translated_blocks=document['blocks'], status='completed',
                chapter_key=captured['chapter_key'],manifest_epoch=captured['manifest_epoch'],
                manifest_revision=captured['manifest_revision'],identity_inferred=False)
            db.add(row); db.flush(); return row
        for number in range(21):
            variant('a' + chr(ord('a') + number), document['content_version'])
        expected = variant('de', document['content_version'])
        # A newer stale edition happens to equal the other chapter's fingerprint.
        # Source matching must be a (chapter, version) pair before ranking.
        variant('de', other['content_version'])
        db.commit()
        page = manifest(db, user.id, novel.id, 0, 1)
        assert page['total'] == 2 and len(page['chapters']) == 1
        row = page['chapters'][0]
        assert row['chapter_number'] == 3 and row['translations_limited'] and len(row['translations']) == 20
        # Remove extra languages to verify the current de survives rank selection.
        db.query(TranslationJob).filter(TranslationJob.language != 'de').delete(synchronize_session=False); db.commit()
        row = manifest(db, user.id, novel.id, 0, 1)['chapters'][0]
        assert not row['translations_limited'] and row['translations'][0]['job_id'] == expected.id
        assert translation_content(db, user.id, expected.id)['document']['blocks'] == document['blocks']
        assert manifest(db, user.id, novel.id, 1, 1)['chapters'][0]['chapter_number'] == 7


def test_followed_start_and_custom_categories_filter_before_count_and_offset(offline_engine):
    from app.models.novel_personal import NovelPersonalData
    with sessionmaker(bind=offline_engine)() as db:
        user = User(username='offline-filter-owner', password='unused'); db.add(user); db.flush()
        library = Library(user_id=user.id, name='Private'); db.add(library); db.flush()
        novel = Novel(library_id=library.id, title='Chapter category fixture'); db.add(novel); db.flush()
        for number, category in [(-2, 'story'), (0, 'story'), (1, 'omake'), (90_000, 'story'), (90_005, 'omake')]:
            db.add(Chapter(novel_id=novel.id, chapter_number=number, category=category, content_status=ContentStatus.MISSING))
        db.commit()
        assert manifest(db, user.id, novel.id, 0, 1, followed_only=True)['chapters'][0]['chapter_number'] == -2
        late = manifest(db, user.id, novel.id, 0, 200, followed_only=True, from_chapter=90_000)
        assert late['total'] == 1 and late['chapters'][0]['chapter_number'] == 90_000
        db.add(NovelPersonalData(user_id=user.id, novel_id=novel.id, followed_categories=['omake'])); db.commit()
        custom = manifest(db, user.id, novel.id, 1, 1, followed_only=True, from_chapter=0)
        assert custom['total'] == 2 and custom['chapters'][0]['chapter_number'] == 90_005
        assert manifest(db, user.id, novel.id, 0, 200)['total'] == 5
