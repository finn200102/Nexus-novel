"""Independent paid accounting qualification; every provider response is synthetic."""
# Imported pytest fixtures intentionally use dependency injection names.
# ruff: noqa: F811
from decimal import Decimal

import pytest

from app.models.translation import ReaderProvider
from app.services.notification_crypto import encrypt_url
from app.services.reader_provider import invoke
from tests.routes.conftest import auth_headers, client, db, test_user  # noqa: F401


@pytest.fixture
def paid(db, test_user):
    provider = ReaderProvider(user_id=test_user.id, name='Private accounting fixture',
        kind='openai_compatible', base_url='https://example.invalid/v1', model='reviewed-model',
        secret_ciphertext=encrypt_url('PRIVATE_API_KEY'), input_price=Decimal('1'), output_price=Decimal('2'),
        budget_microusd=1_000_000, used_microusd=100, reserved_microusd=77)
    db.add(provider)
    db.commit()
    return provider


def response(text='Translated passage'):
    return {'choices': [{'message': {'content': text}, 'finish_reason': 'stop'}],
        'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}


def test_completed_call_preserves_unattributed_legacy_aggregates(db, paid):
    calls = []
    def provider_request(provider, **kwargs):
        calls.append(kwargs)
        return response()
    text, incoming, outgoing, charged = invoke(db, paid, prompt='PRIVATE_SOURCE', system='PRIVATE_SYSTEM', request=provider_request)
    assert (text, incoming, outgoing, charged) == ('Translated passage', 10, 5, 20)
    db.refresh(paid)
    assert (paid.used_microusd, paid.reserved_microusd) == (120, 77)
    assert len(calls) == 1


def test_dispatch_and_charge_use_reviewed_snapshot_despite_concurrent_price_edit(db, paid):
    original_id = paid.id
    def provider_request(provider, **kwargs):
        assert (provider.model, provider.base_url) == ('reviewed-model', 'https://example.invalid/v1')
        # A separately committed settings edit during the network request must
        # never reprice this already dispatched request or expose its new key.
        from sqlalchemy.orm import Session
        with Session(bind=db.bind) as settings:
            current = settings.get(ReaderProvider, original_id)
            current.input_price = Decimal('10')
            current.output_price = Decimal('20')
            settings.commit()
        return response()
    result = invoke(db, paid, prompt='PRIVATE_SOURCE', system='PRIVATE_SYSTEM', request=provider_request)
    assert result[3] == 20
    db.refresh(paid)
    assert (paid.used_microusd, paid.reserved_microusd) == (120, 77)
    assert (paid.input_price, paid.output_price) == (Decimal('10'), Decimal('20'))


# The shared fixture creates and drops a unique PostgreSQL schema per test.
from tests.database.test_reading_run_migration import run_engine  # noqa: E402,F401


def _ledger_seed(engine):
    from sqlalchemy.orm import sessionmaker
    from app.models.base import BaseModel
    from app.models import User
    BaseModel.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        owner = User(username='ledger-concurrency-owner', password='unused')
        session.add(owner); session.flush()
        provider = ReaderProvider(user_id=owner.id, name='Concurrent private ledger',
            kind='openai_compatible', base_url='https://example.invalid/v1', model='synthetic',
            input_price=1, output_price=2, budget_microusd=1000, used_microusd=100, reserved_microusd=77)
        session.add(provider); session.commit()
        return factory, owner.id, provider.id


def test_postgres_reconcile_and_late_response_have_one_accounting_winner(run_engine):
    if run_engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL row-lock qualification')
    from concurrent.futures import ThreadPoolExecutor
    from datetime import timedelta
    from threading import Barrier
    from types import SimpleNamespace
    from fastapi import HTTPException
    from app.models.translation import ReaderProviderRequest, ReaderProviderReconciliationOperation
    from app.services import reader_provider_usage as ledger
    from app.services.job_lease import utcnow
    factory, owner_id, provider_id = _ledger_seed(run_engine)
    with factory() as session:
        row = ledger.reserve_request(session, session.get(ReaderProvider, provider_id), 200)
        key = row.request_key
        row.expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
    barrier = Barrier(2)
    def finish(manual):
        with factory() as session:
            barrier.wait()
            try:
                if manual:
                    ledger.reconcile(session, owner_id, provider_id, key,
                        SimpleNamespace(expected_revision=0, operation_id='concurrent-manual', actual_microusd=31))
                else:
                    ledger.settle_request(session, key, charged=20, input_tokens=10, output_tokens=5)
                return 'manual' if manual else 'response'
            except (HTTPException, ledger.ProviderRequestUnresolved):
                session.rollback()
                return 'fenced'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(finish, [False, True]))
    assert results.count('fenced') == 1
    with factory() as session:
        row = session.query(ReaderProviderRequest).one()
        provider = session.get(ReaderProvider, provider_id)
        assert provider.reserved_microusd == 77
        assert row.revision == 1
        assert provider.used_microusd == 100 + row.actual_microusd
        assert (row.status, row.actual_microusd) in [('completed', 20), ('reconciled', 31)]
        assert session.query(ReaderProviderReconciliationOperation).count() == (row.status == 'reconciled')


def test_postgres_reservation_waits_for_reconciliation_before_budget_decision(run_engine):
    if run_engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL row-lock qualification')
    from concurrent.futures import ThreadPoolExecutor, TimeoutError
    from threading import Event
    from types import SimpleNamespace
    from app.models import User
    from app.models.translation import ReaderProviderRequest
    from app.services import reader_provider_usage as ledger
    factory, owner_id, provider_id = _ledger_seed(run_engine)
    with factory() as session:
        provider = session.get(ReaderProvider, provider_id)
        row = ledger.reserve_request(session, provider, 200)
        key = row.request_key
        ledger.mark_unknown(session, key)
        provider = session.get(ReaderProvider, provider_id)
        provider.budget_microusd = 400
        session.commit()
    with factory() as reviewer:
        reviewer.query(User).filter_by(id=owner_id).with_for_update().one()
        started = Event()
        def reserve_after_review():
            with factory() as session:
                provider = session.get(ReaderProvider, provider_id)
                started.set()
                return ledger.reserve_request(session, provider, 200).request_key
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(reserve_after_review)
            assert started.wait(5)
            try:
                with pytest.raises(TimeoutError):
                    future.result(timeout=.1)
            finally:
                ledger.reconcile(reviewer, owner_id, provider_id, key,
                    SimpleNamespace(expected_revision=1, operation_id='release-before-dispatch', actual_microusd=0))
            assert future.result(timeout=5) != key
    with factory() as session:
        provider = session.get(ReaderProvider, provider_id)
        assert (provider.used_microusd, provider.reserved_microusd) == (100, 277)
        assert provider.used_microusd + provider.reserved_microusd <= provider.budget_microusd
        assert session.query(ReaderProviderRequest).count() == 2


@pytest.mark.parametrize('field,value', [('base_url', 'https://other.invalid/v1'), ('model', 'unreviewed-model'), ('input_price', Decimal('10'))])
def test_settings_changed_after_permission_check_abort_before_any_dispatch(db, paid, field, value):
    from sqlalchemy.orm import Session
    from app.models.translation import ReaderProviderRequest
    # Keep the caller's previously reviewed settings loaded, as consent and
    # chapter jobs do before entering the shared invocation boundary.
    assert paid.base_url == 'https://example.invalid/v1'
    assert paid.model == 'reviewed-model' and paid.input_price == Decimal('1')
    with Session(bind=db.bind) as settings:
        setattr(settings.get(ReaderProvider, paid.id), field, value)
        settings.commit()
    calls = []
    def transport(*args, **kwargs):
        calls.append(kwargs)
        return response()
    with pytest.raises(ValueError, match='changed'):
        invoke(db, paid, prompt='PRIVATE_SOURCE', system='PRIVATE_SYSTEM', request=transport)
    assert calls == [] and db.query(ReaderProviderRequest).count() == 0
    db.refresh(paid)
    assert (paid.used_microusd, paid.reserved_microusd) == (100, 77)


@pytest.mark.parametrize('actual', [0, 31])
def test_unknown_call_reconciliation_is_private_idempotent_and_legacy_safe(client, db, paid, auth_headers, actual):
    from app.models import User
    from tests.auth_helpers import bearer_headers
    from app.services import reader_provider_usage as ledger
    from app.models.translation import ReaderProviderRequest
    def timeout(*args, **kwargs):
        raise TimeoutError('PRIVATE_API_KEY PRIVATE_SOURCE raw provider payload')
    with pytest.raises(ledger.ProviderRequestUnresolved):
        invoke(db, paid, prompt='PRIVATE_SOURCE', system='PRIVATE_SYSTEM', request=timeout)
    row = db.query(ReaderProviderRequest).one()
    url = f'/reader/providers/{paid.id}/requests'
    listing = client.get(url, headers=auth_headers)
    assert listing.status_code == 200 and listing.headers['cache-control'] == 'private, no-store'
    body = listing.json()
    assert body['total'] == 1 and body['items'][0]['status'] == 'unknown'
    assert body['items'][0]['can_reconcile'] is True
    for secret in ('PRIVATE_API_KEY', 'PRIVATE_SOURCE', 'PRIVATE_SYSTEM', 'raw provider payload', 'secret_ciphertext'):
        assert secret not in listing.text
    ownerless = User(username='foreign-ledger-reader', password='unused')
    db.add(ownerless); db.commit()
    foreign_headers = bearer_headers(ownerless.id, db)
    request = dict(expected_revision=row.revision, operation_id='independent-reconciliation', actual_microusd=actual)
    reconcile_url = f'{url}/{row.request_key}/reconcile'
    assert client.get(url, headers=foreign_headers).status_code == 404
    assert client.post(reconcile_url, headers=foreign_headers, json=request).status_code == 404
    first = client.post(reconcile_url, headers=auth_headers, json=request)
    assert first.status_code == 200, first.text
    assert first.json()['item']['actual_microusd'] == actual
    assert first.json()['accounting']['reserved_microusd'] == 77
    assert first.json()['accounting']['used_microusd'] == 100 + actual
    assert client.post(reconcile_url, headers=auth_headers, json=request).json() == first.json()
    assert client.post(reconcile_url, headers=auth_headers, json={**request, 'actual_microusd': actual + 1}).status_code == 409
    assert client.post(reconcile_url, headers=auth_headers, json={**request, 'operation_id': 'other-review'}).status_code == 409
    db.refresh(paid)
    assert (paid.used_microusd, paid.reserved_microusd) == (100 + actual, 77)
    # Live financial state is instance data, never accepted as portable library
    # import/export that could recreate spendable reservations elsewhere.
    exported = client.get('/me/export', headers=auth_headers)
    assert exported.status_code == 200
    for private in ('PRIVATE_API_KEY', row.request_key, 'reader_provider_requests', 'reserved_microusd'):
        assert private not in exported.text


def test_expired_pending_reconciled_during_transport_discards_late_text(client, db, paid, auth_headers):
    from datetime import timedelta
    from sqlalchemy.orm import Session
    from app.models.translation import ReaderProviderRequest
    from app.services import reader_provider_usage as ledger
    from app.services.job_lease import utcnow
    calls = []
    def late_response(*args, **kwargs):
        calls.append(True)
        with Session(bind=db.bind) as other:
            row = other.query(ReaderProviderRequest).one()
            key = row.request_key
            row.expires_at = utcnow() - timedelta(seconds=1)
            other.commit()
        reviewed = client.post(f'/reader/providers/{paid.id}/requests/{key}/reconcile', headers=auth_headers,
            json=dict(expected_revision=0, operation_id='late-response-manual-review', actual_microusd=31))
        assert reviewed.status_code == 200, reviewed.text
        return response('LATE TEXT MUST NOT BE USED')
    with pytest.raises(ledger.ProviderRequestUnresolved, match='late response'):
        invoke(db, paid, prompt='PRIVATE_SOURCE', system='PRIVATE_SYSTEM', request=late_response)
    db.refresh(paid)
    assert calls == [True] and (paid.used_microusd, paid.reserved_microusd) == (131, 77)
    row = db.query(ReaderProviderRequest).one()
    assert (row.status, row.actual_microusd, row.revision) == ('reconciled', 31, 1)


@pytest.mark.parametrize('crash_after_charge', [False, True])
def test_worker_restart_never_resends_ambiguous_or_settled_unsaved_paid_paragraph(db, paid, test_user, monkeypatch, crash_after_charge):
    from contextlib import nullcontext
    from datetime import timedelta
    from sqlalchemy.orm import sessionmaker
    from app.models import Chapter, Library, Novel
    from app.models.translation import ReaderProviderRequest, TranslationJob
    from app.models.story_processing_permission import StoryProcessingPermission
    from app.services.chapter_document import from_html
    from app.services import translation_service as worker
    from app.services.job_lease import utcnow
    library = Library(user_id=test_user.id, name='Worker recovery library')
    db.add(library); db.flush()
    novel = Novel(library_id=library.id, title='Private crash recovery original')
    db.add(novel); db.flush()
    document = from_html('<p>First private paragraph.</p><p>Second untouched paragraph.</p>')
    chapter = Chapter(novel_id=novel.id, chapter_number=3, document=document, content=document['plain_text'])
    db.add(chapter)
    db.add(StoryProcessingPermission(user_id=test_user.id, novel_id=novel.id, provider_id=paid.id,
        translation=True, companion=False))
    db.commit()
    job = worker.queue_translation(db, test_user, novel, chapter, paid, 'de')
    job_id = job.id
    calls = []
    def transport(*args, **kwargs):
        calls.append(kwargs['prompt'])
        if not crash_after_charge:
            raise SystemExit('Synthetic hard worker termination during request')
        return response()
    monkeypatch.setattr('app.services.reader_provider.direct_request', transport)
    monkeypatch.setattr(worker, 'heartbeat', lambda *args: nullcontext())
    real_translate = worker.translate_block
    def crash_before_paragraph_commit(*args, **kwargs):
        real_translate(*args, **kwargs)
        raise SystemExit('Synthetic hard termination after financial commit')
    if crash_after_charge:
        monkeypatch.setattr(worker, 'translate_block', crash_before_paragraph_commit)
    factory = sessionmaker(bind=db.bind)
    with pytest.raises(SystemExit):
        worker.process_translation(job_id, factory)
    monkeypatch.setattr(worker, 'translate_block', real_translate)
    db.expire_all()
    interrupted = db.get(TranslationJob, job_id)
    assert interrupted.translated_blocks == []
    interrupted.lease_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    worker.process_due_translations(factory)
    db.expire_all()
    recovered = db.get(TranslationJob, job_id)
    assert recovered.status == 'failed' and recovered.error_code == 'PAID_REQUEST_UNRESOLVED'
    assert recovered.translated_blocks == [] and len(calls) == 1
    assert db.query(ReaderProviderRequest).count() == 1
    request = db.query(ReaderProviderRequest).one()
    assert request.status == ('completed' if crash_after_charge else 'pending')
    assert db.get(Chapter, chapter.id).document == document
    db.refresh(paid)
    assert paid.used_microusd == (120 if crash_after_charge else 100)
    assert paid.reserved_microusd == (77 if crash_after_charge else 77 + request.reserved_microusd)


@pytest.mark.parametrize('field,value', [('base_url', 'https://other.invalid/v1'), ('model', 'late-unreviewed-model'), ('output_price', Decimal('20'))])
def test_settings_change_between_quote_and_atomic_reservation_cannot_dispatch(db, paid, monkeypatch, field, value):
    from sqlalchemy.orm import Session
    from app.models.translation import ReaderProviderRequest
    from app.services import reader_provider_usage as ledger
    reserve = ledger.reserve_request
    def changed_settings(session, provider, amount, **kwargs):
        with Session(bind=db.bind) as settings:
            setattr(settings.get(ReaderProvider, paid.id), field, value)
            settings.commit()
        return reserve(session, provider, amount, **kwargs)
    monkeypatch.setattr(ledger, 'reserve_request', changed_settings)
    calls = []
    def transport(*args, **kwargs):
        calls.append(True)
        return response()
    with pytest.raises(ValueError, match='changed'):
        invoke(db, paid, prompt='PRIVATE_SOURCE', system='PRIVATE_SYSTEM', request=transport)
    db.rollback()
    assert calls == [] and db.query(ReaderProviderRequest).count() == 0
    db.refresh(paid)
    assert (paid.used_microusd, paid.reserved_microusd) == (100, 77)


@pytest.mark.parametrize('usage', [{}, {'prompt_tokens': True, 'completion_tokens': 5},
    {'prompt_tokens': -1, 'completion_tokens': 5}, {'prompt_tokens': 10, 'completion_tokens': 1.5}])
def test_unknown_metering_never_becomes_fabricated_actual_charge(db, paid, usage):
    from app.models.translation import ReaderProviderRequest
    from app.services import reader_provider_usage as ledger
    value = response()
    value['usage'] = usage
    with pytest.raises(ledger.ProviderRequestUnresolved):
        invoke(db, paid, prompt='PRIVATE_SOURCE', system='PRIVATE_SYSTEM', request=lambda *args, **kwargs: value)
    db.refresh(paid)
    row = db.query(ReaderProviderRequest).one()
    assert row.status == 'unknown' and row.actual_microusd is None
    assert paid.used_microusd == 100 and paid.reserved_microusd == 77 + row.reserved_microusd


def test_metered_truncation_is_charged_even_when_text_cannot_be_used(db, paid):
    from app.models.translation import ReaderProviderRequest
    value = response()
    value['choices'][0]['finish_reason'] = 'length'
    with pytest.raises(ValueError, match='truncated'):
        invoke(db, paid, prompt='PRIVATE_SOURCE', system='PRIVATE_SYSTEM', request=lambda *args, **kwargs: value)
    db.refresh(paid)
    row = db.query(ReaderProviderRequest).one()
    assert (row.status, row.actual_microusd) == ('completed', 20)
    assert (paid.used_microusd, paid.reserved_microusd) == (120, 77)


def test_upgrade_pauses_preledger_paid_work_even_when_no_reservation_remains(run_engine):
    from datetime import datetime, timedelta
    from alembic import command
    from sqlalchemy import MetaData, Table, select
    from app.db_migrations import alembic_config
    with run_engine.connect() as connection:
        command.upgrade(alembic_config(connection), '0043')
        connection.commit()
        metadata = MetaData()
        tables = {name: Table(name, metadata, autoload_with=connection) for name in
            ('users', 'libraries', 'novels', 'chapters', 'reader_providers', 'translation_jobs')}
        connection.execute(tables['users'].insert().values(id=1, username='legacy-ledger-owner', password='unused', storage_id='legacy-ledger-owner'))
        connection.execute(tables['libraries'].insert().values(id=1, user_id=1, name='Private'))
        connection.execute(tables['novels'].insert().values(id=1, library_id=1, title='Private legacy translation'))
        connection.execute(tables['chapters'].insert().values(id=1, novel_id=1, chapter_number=3,
            content_status='PRESENT', audio_status='MISSING', retry_count=0))
        for provider_id, kind, reserved in [(1, 'openai_compatible', 0), (2, 'anthropic', 77), (3, 'local', 0), (4, 'local_translation', 0)]:
            connection.execute(tables['reader_providers'].insert().values(id=provider_id, user_id=1,
                name='Legacy provider', kind=kind, base_url='https://unused.invalid/v1', model='legacy',
                used_microusd=123, reserved_microusd=reserved, budget_microusd=1000))
        completed = [{'id': 'original-block', 'text': 'Already translated', 'html': '<p>Already translated</p>'}]
        states = {}
        job_id = 0
        for provider_id in (1, 2, 3, 4):
            for status in ('processing', 'retry_wait', 'queued'):
                job_id += 1
                pristine = status == 'queued'
                states[job_id] = (provider_id, status)
                connection.execute(tables['translation_jobs'].insert().values(id=job_id, user_id=1, novel_id=1,
                    chapter_id=1, provider_id=provider_id, language='de', fingerprint=str(job_id), source_version='a' * 64,
                    provider_snapshot={'model': 'legacy'}, source_blocks=[{'id': 'original-block'}, {'id': 'pending-block'}],
                    glossary={}, translated_blocks=[] if pristine else completed, status=status,
                    attempt_count=0 if pristine else 1, lease_owner=None if pristine else 'old-worker',
                    lease_expires_at=None if pristine else datetime.now() + timedelta(minutes=10),
                    next_attempt_at=datetime.now() - timedelta(minutes=1), input_tokens=0 if pristine else 10,
                    output_tokens=0 if pristine else 5, charged_microusd=0 if pristine else 20))
        connection.commit()
        command.upgrade(alembic_config(connection), '0044')
        connection.commit()
        jobs = Table('translation_jobs', MetaData(), autoload_with=connection)
        for row in connection.execute(select(jobs)).mappings():
            provider_id, original_status = states[row['id']]
            should_pause = provider_id in (1, 2) and original_status in ('processing', 'retry_wait')
            assert row['status'] == ('failed' if should_pause else original_status)
            assert row['translated_blocks'] == ([] if original_status == 'queued' else completed)
            assert row['paid_retry_generation'] == 0
            assert (row['input_tokens'], row['output_tokens'], row['charged_microusd']) == ((0, 0, 0) if original_status == 'queued' else (10, 5, 20))
            if should_pause:
                assert row['error_code'] == 'LEGACY_PAID_REVIEW_REQUIRED'
                assert row['lease_owner'] is None and row['lease_expires_at'] is None
                assert row['next_attempt_at'] is None and row['finished_at'] is not None
        providers = Table('reader_providers', MetaData(), autoload_with=connection)
        assert connection.execute(select(providers.c.used_microusd, providers.c.reserved_microusd).order_by(providers.c.id)).all() == [(123, 0), (123, 77), (123, 0), (123, 0)]
        ledger = Table('reader_provider_requests', MetaData(), autoload_with=connection)
        rows = connection.execute(select(ledger)).mappings().all()
        assert len(rows) == 1
        assert (rows[0]['provider_id'], rows[0]['status'], rows[0]['reserved_microusd']) == (2, 'legacy_unknown', 77)
        assert rows[0]['translation_job_id'] is None and rows[0]['input_tokens'] is None and rows[0]['actual_microusd'] is None


def test_ledger_timestamps_explicitly_identify_utc(client, db, paid, auth_headers):
    from datetime import datetime, timezone
    from app.models.translation import ReaderProviderRequest
    from app.services import reader_provider_usage as ledger
    row = ledger.reserve_request(db, paid, 200)
    key = row.request_key
    ledger.mark_unknown(db, key)
    unknown = db.query(ReaderProviderRequest).one()
    result = client.post(f'/reader/providers/{paid.id}/requests/{key}/reconcile', headers=auth_headers,
        json=dict(expected_revision=unknown.revision, operation_id='utc-display', actual_microusd=0))
    assert result.status_code == 200
    for field in ('created_at', 'expires_at', 'resolved_at'):
        value = result.json()['item'][field]
        instant = datetime.fromisoformat(value.replace('Z', '+00:00'))
        assert instant.tzinfo is not None, f'{field} must not parse as local browser time: {value}'
        assert instant.utcoffset() == timezone.utc.utcoffset(instant)


def test_migrated_job_retry_requires_review_of_unattributed_provider_reservation(db, paid, test_user):
    from types import SimpleNamespace
    from uuid import uuid4
    from fastapi import HTTPException
    from app.models.translation import ReaderProviderRequest
    from app.services import reader_provider_usage as ledger
    key = str(uuid4())
    db.add(ReaderProviderRequest(request_key=key, user_id=test_user.id, provider_id=paid.id,
        model_snapshot={'kind': 'legacy_unknown', 'base_url': '', 'model': 'Unknown legacy request',
            'input_price': '0', 'output_price': '0'}, status='legacy_unknown', revision=0, reserved_microusd=77))
    db.commit()
    job = SimpleNamespace(id=777, user_id=test_user.id, provider_id=paid.id, paid_retry_generation=0,
        error_code='LEGACY_PAID_REVIEW_REQUIRED', status='failed')
    with pytest.raises(HTTPException) as blocked:
        ledger.require_retry_review(db, job)
    assert blocked.value.status_code == 409
    assert job.paid_retry_generation == 0
    ledger.reconcile(db, test_user.id, paid.id, key,
        SimpleNamespace(expected_revision=0, operation_id='review-legacy-before-retry', actual_microusd=0))
    ledger.require_retry_review(db, job)
    assert job.paid_retry_generation == 1
