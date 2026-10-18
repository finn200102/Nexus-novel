from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import event
from app.models.translation import ReaderProvider, ReaderProviderRequest
from app.services import reader_provider_usage as usage
from app.services.reader_provider import invoke
from app.services.notification_crypto import encrypt_url
from app.services.job_lease import utcnow


@pytest.fixture
def paid_provider(db, test_user):
    provider = ReaderProvider(user_id=test_user.id, name='Paid fixture', kind='openai_compatible',
        base_url='https://provider.invalid/v1', model='immutable-model', secret_ciphertext=encrypt_url('fixture-secret'),
        input_price=1, output_price=2, budget_microusd=1_000_000)
    db.add(provider); db.commit()
    return provider


def test_reservation_and_ledger_rollback_together_before_dispatch(db, paid_provider):
    def refuse(mapper, connection, target):
        raise RuntimeError('Simulated database failure')
    event.listen(ReaderProviderRequest, 'before_insert', refuse)
    try:
        with pytest.raises(RuntimeError):
            usage.reserve_request(db, paid_provider, 400)
    finally:
        event.remove(ReaderProviderRequest, 'before_insert', refuse)
    db.refresh(paid_provider)
    assert paid_provider.reserved_microusd == 0
    assert db.query(ReaderProviderRequest).count() == 0


@pytest.mark.parametrize('invalid', [None, -1, True, 1.5, '2', 10_000_001])
def test_paid_invalid_usage_never_invents_actual_charge(db, paid_provider, invalid):
    def response(*args, **kwargs):
        return {'choices': [{'message': {'content': 'Safe prose'}, 'finish_reason': 'stop'}],
            'usage': {'prompt_tokens': invalid, 'completion_tokens': 4}}
    with pytest.raises(usage.ProviderRequestUnresolved):
        invoke(db, paid_provider, prompt='Source', system='Translate', request=response)
    db.refresh(paid_provider)
    row = db.query(ReaderProviderRequest).one()
    assert row.status == 'unknown' and row.actual_microusd is None
    assert paid_provider.used_microusd == 0 and paid_provider.reserved_microusd == row.reserved_microusd > 0


def test_pending_expiry_reconciliation_fences_late_reply_and_idempotent_receipt(client, db, paid_provider, auth_headers):
    row = usage.reserve_request(db, paid_provider, 500)
    url = f'/reader/providers/{paid_provider.id}/requests/{row.request_key}/reconcile'
    value = dict(expected_revision=0, operation_id=str(uuid4()), actual_microusd=0)
    active = client.post(url, json=value, headers=auth_headers)
    assert active.status_code == 409 and active.json()['detail']['code'] == 'request_inflight'
    row.expires_at = utcnow() - timedelta(seconds=1); db.commit()
    accepted = client.post(url, json=value, headers=auth_headers)
    assert accepted.status_code == 200
    assert accepted.json()['accounting']['reserved_microusd'] == 0
    assert accepted.json()['item']['actual_microusd'] == 0
    assert client.post(url, json=value, headers=auth_headers).json() == accepted.json()
    with pytest.raises(usage.ProviderRequestUnresolved):
        usage.settle_request(db, row.request_key, charged=99, input_tokens=1, output_tokens=49)
    db.refresh(paid_provider)
    assert paid_provider.used_microusd == paid_provider.reserved_microusd == 0
    changed = client.post(url, json={**value, 'actual_microusd': 1}, headers=auth_headers)
    assert changed.status_code == 409 and changed.json()['detail']['code'] == 'operation_id_reused'


def test_budget_rejection_has_no_ledger_or_provider_calls(db, paid_provider):
    paid_provider.budget_microusd = 1; db.commit()
    def forbidden(*args, **kwargs):
        raise AssertionError('No paid request when budget insufficient')
    with pytest.raises(ValueError, match='budget'):
        invoke(db, paid_provider, prompt='Source', system='Translate', request=forbidden)
    assert db.query(ReaderProviderRequest).count() == 0
    db.refresh(paid_provider)
    assert paid_provider.reserved_microusd == paid_provider.used_microusd == 0


def test_paid_truncation_with_known_usage_settles_actual(db, paid_provider):
    def response(*args, **kwargs):
        return {'choices': [{'message': {'content': 'Partial'}, 'finish_reason': 'length'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
    with pytest.raises(ValueError, match='truncated'):
        invoke(db, paid_provider, prompt='Source', system='Translate', request=response)
    row = db.query(ReaderProviderRequest).one()
    assert row.status == 'completed' and row.actual_microusd == 20
    db.refresh(paid_provider)
    assert paid_provider.used_microusd == 20 and paid_provider.reserved_microusd == 0
