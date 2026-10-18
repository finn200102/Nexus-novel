"""Synthetic private guide accounting and independent portrait authorization."""
# ruff: noqa: F811
import base64
import struct
import zlib
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.models.translation import ReaderProviderRequest
from app.models.story_processing_permission import StoryProcessingPermission
from app.services import reader_provider as provider_service, reader_provider_usage as ledger, processing_permissions
from tests.contracts.test_paid_provider_ledger_qualification import paid, response  # noqa: F401
from tests.routes.test_reader_tools import story


def guide_provider(db, paid):
    paid.capabilities = ['translation', 'companion', 'guide_text', 'guide_portrait']
    paid.image_model = 'explicit-image-model'; paid.image_price_microusd = 50000
    paid.image_sizes = ['1024x1024']; paid.image_qualities = ['medium']
    db.commit()
    return paid


def png(width=1024, height=1024):
    def chunk(kind, body):
        return struct.pack('>I', len(body)) + kind + body + struct.pack('>I', zlib.crc32(kind + body) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\0' * (height * (1 + width * 3)))) + chunk(b'IEND', b'')


def invoke(db, provider, key, generation=0, **kwargs):
    return provider_service.invoke(db, provider, prompt='Only already-read evidence', system='Bounded', purpose='guide_extract',
        job_key=key, item_key='0', retry_generation=generation, authorize=lambda: None, **kwargs)


def test_completed_paid_step_without_artifact_cannot_be_resent_automatically(db, paid):
    provider = guide_provider(db, paid); key = str(uuid4()); calls = []
    def request(*_, **__): calls.append(1); return response('Cited guide')
    assert invoke(db, provider, key, request=request)[0] == 'Cited guide'
    with pytest.raises(ledger.ProviderRequestUnresolved): invoke(db, provider, key, request=request)
    assert len(calls) == 1
    row = db.query(ReaderProviderRequest).filter_by(job_key=key).one()
    assert (row.purpose, row.item_key, row.status) == ('guide_extract', '0', 'completed')
    # Explicit retry generation is an intentional new request, not lease recovery.
    assert invoke(db, provider, key, generation=1, request=request)[0] == 'Cited guide'
    assert len(calls) == 2


def test_unknown_request_blocks_all_generations_until_reconciliation(db, paid):
    provider = guide_provider(db, paid); key = str(uuid4())
    def lost(*_, **__): raise TimeoutError('Lost provider response')
    with pytest.raises(ledger.ProviderRequestUnresolved): invoke(db, provider, key, request=lost)
    with pytest.raises(ledger.ProviderRequestUnresolved): invoke(db, provider, key, generation=1, request=lambda *_a, **_k: response())
    row = db.query(ReaderProviderRequest).filter_by(job_key=key).one()
    with pytest.raises(Exception) as blocked: ledger.require_job_retry_review(db, provider.user_id, key)
    assert blocked.value.status_code == 409
    ledger.reconcile(db, provider.user_id, provider.id, row.request_key, SimpleNamespace(expected_revision=row.revision, actual_microusd=0, operation_id=str(uuid4())))
    assert invoke(db, provider, key, generation=1, request=lambda *_a, **_k: response())[0] == 'Translated passage'


def test_generic_step_requires_fresh_authorization_and_configuration_before_network(db, paid):
    provider = guide_provider(db, paid); calls = []
    def request(*_, **__): calls.append(1); return response()
    with pytest.raises(PermissionError):
        provider_service.invoke(db, provider, prompt='evidence', system='bound', purpose='guide_extract',
            job_key=str(uuid4()), item_key='0', retry_generation=0, request=request)
    def changed():
        provider.model = 'changed-before-reservation'; db.commit()
    with pytest.raises(ValueError, match='configuration changed'):
        provider_service.invoke(db, provider, prompt='evidence', system='bound', purpose='guide_extract',
            job_key=str(uuid4()), item_key='0', retry_generation=0, authorize=changed, request=request)
    assert calls == [] and db.query(ReaderProviderRequest).count() == 0


def test_portrait_patch_is_scoped_and_old_text_ao3_grant_never_authorizes_images(client, db, test_library, auth_headers, paid):
    provider = guide_provider(db, paid); novel, _, _ = story(db, test_library)
    novel.novel_site = 'archive'
    permission = StoryProcessingPermission(user_id=provider.user_id, novel_id=novel.id, provider_id=provider.id,
        translation=True, companion=True, ao3_consent=True)
    db.add(permission); db.commit()
    with pytest.raises(PermissionError): processing_permissions.check(db, provider.user_id, novel, provider, 'portrait', consent=True, ao3_consent=True)
    path = f'/reader/permissions/{novel.id}/{provider.id}/portrait'
    assert client.patch(path, headers=auth_headers, json={'portrait': True}).status_code == 422
    result = client.patch(path, headers=auth_headers, json={'portrait': True, 'portrait_ao3_consent': True})
    assert result.status_code == 200, result.text
    assert result.json()['translation'] and result.json()['companion'] and result.json()['ao3_consent']
    processing_permissions.check(db, provider.user_id, novel, provider, 'portrait')
    provider.image_model = 'different-image-model'; db.commit()
    with pytest.raises(PermissionError): processing_permissions.check(db, provider.user_id, novel, provider, 'portrait')
    state = client.get(f'/reader/permissions/{novel.id}/{provider.id}', headers=auth_headers).json()
    assert state['portrait'] is False and state['portrait_requires_review'] is True


def test_inline_png_portrait_charges_declared_ceiling_once_and_never_fetches_url(db, paid):
    provider = guide_provider(db, paid); key = str(uuid4()); calls = []
    def image(*_, **kwargs):
        calls.append(kwargs)
        return {'data': [{'b64_json': base64.b64encode(png()).decode()}]}
    args = dict(prompt='Alice in observed harbour', purpose='guide_portrait', job_key=key, item_key='image', retry_generation=0, authorize=lambda: None, request=image)
    body, mime, charged = provider_service.invoke_image(db, provider, **args)
    assert body == png() and mime == 'image/png' and charged == 50000
    with pytest.raises(ledger.ProviderRequestUnresolved): provider_service.invoke_image(db, provider, **args)
    assert len(calls) == 1 and calls[0]['image_quality'] == 'medium'
    assert db.query(ReaderProviderRequest).filter_by(job_key=key).one().actual_microusd == 50000


@pytest.mark.parametrize('value', [{'url':'http://127.0.0.1/private'}, {'b64_json':'<svg>script</svg>'}, {'b64_json':base64.b64encode(png(1,1)).decode()}])
def test_bad_image_payload_keeps_unknown_reservation_and_never_downloads_url(db, paid, value):
    provider = guide_provider(db, paid); key = str(uuid4())
    with pytest.raises(ledger.ProviderRequestUnresolved):
        provider_service.invoke_image(db, provider, prompt='Alice', purpose='guide_portrait', job_key=key,
            item_key='image', retry_generation=0, authorize=lambda: None, request=lambda *_a, **_k: {'data':[value]})
    row = db.query(ReaderProviderRequest).filter_by(job_key=key).one()
    assert row.status == 'unknown' and row.reserved_microusd == 50000


def test_local_generic_authorization_releases_all_transactions_before_inference(db, test_user, monkeypatch):
    from app.models.translation import ReaderProvider
    from app.models.user import User
    monkeypatch.setenv('NEXUS_LOCAL_AI_BASE_URL', 'http://local-guide.invalid/v1')
    provider = ReaderProvider(user_id=test_user.id, name='Explicit local', kind='local', base_url='http://local-guide.invalid/v1',
        model='local-guide', capabilities=['guide_text'])
    db.add(provider); db.commit()
    def authorize():
        db.query(User).filter_by(id=test_user.id).with_for_update().one()
    def request(*_args, **_kwargs):
        assert not db.in_transaction(), 'No account/job/permission lock may survive into model I/O'
        return response('Local observed fact')
    result = provider_service.invoke(db, provider, prompt='Read evidence', system='Bounded', purpose='guide_extract',
        job_key=str(uuid4()), item_key='0', retry_generation=0, authorize=authorize, request=request)
    assert result[0] == 'Local observed fact' and result[3] == 0


def test_anthropic_cannot_declare_image_capability_and_old_defaults_do_not_enable_guides(client, auth_headers):
    result = client.post('/reader/providers', headers=auth_headers, json={'name':'Unsupported image protocol', 'kind':'anthropic',
        'base_url':'https://example.invalid/v1','model':'explicit-text','capabilities':['guide_portrait'],
        'image_model':'imaginary-image-model','image_price_usd':.1,'image_sizes':['1024x1024'],'image_qualities':['medium']})
    assert result.status_code == 422
    result = client.post('/reader/providers', headers=auth_headers, json={'name':'Legacy text', 'kind':'anthropic',
        'base_url':'https://example.invalid/v1','model':'explicit-text'})
    assert result.status_code == 201
    assert result.json()['capabilities'] == ['translation','companion']


def test_stateless_adapters_remove_wrong_operation_fields_and_send_explicit_models(monkeypatch):
    import json
    from app.services import companion_client
    calls = []
    monkeypatch.setattr(companion_client, '_guide_call', lambda path, body, maximum: calls.append((path,body,maximum)) or response())
    selected = SimpleNamespace(kind='openai_compatible', base_url='https://chosen.invalid/v1', model='text-model', image_model='image-model')
    prompt = json.dumps({'operation':'extract','through_chapter':-2,'evidence':[{'chapter':-2,'block_id':'past','text':'Alice arrives.'}],
        'observations':[],'portrait_subject':None,'provider':{'model':'MUST_NOT_OVERRIDE'}})
    companion_client.guide_request(selected, prompt=prompt, system='ignored fixed server recipe', max_tokens=4096, api_key='synthetic-key')
    assert 'portrait_subject' not in calls[-1][1] and calls[-1][1]['provider']['model']=='text-model'
    image = json.dumps({'operation':'portrait','through_chapter':-2,'evidence':[{'chapter':-2,'block_id':'past','text':'Alice arrives.'}],
        'observations':[],'portrait_subject':'Alice'})
    companion_client.image_request(selected, prompt=image, system='ignored', image_size='1024x1024', image_quality='medium', api_key='synthetic-key')
    assert calls[-1][0]=='portrait' and 'operation' not in calls[-1][1]
    assert calls[-1][1]['provider']['model']=='image-model'


def test_portrait_only_new_permission_keeps_both_text_decisions_unset(client, db, test_library, auth_headers, paid):
    provider = guide_provider(db, paid); novel, _, _ = story(db, test_library)
    result = client.patch(f'/reader/permissions/{novel.id}/{provider.id}/portrait', headers=auth_headers, json={'portrait': True})
    assert result.status_code == 200, result.text
    assert result.json()['translation'] is None and result.json()['companion'] is None
    row = db.query(StoryProcessingPermission).filter_by(novel_id=novel.id, provider_id=provider.id).one()
    assert row.translation is None and row.companion is None and row.ao3_consent is False
    # Previously undecided text still requires explicit consent, rather than becoming a denial.
    processing_permissions.check(db, provider.user_id, novel, provider, 'translation', consent=True)
    row.translation = False; row.companion = False; db.commit()
    result = client.patch(f'/reader/permissions/{novel.id}/{provider.id}/portrait', headers=auth_headers, json={'portrait': False})
    assert result.json()['translation'] is False and result.json()['companion'] is False
    with pytest.raises(PermissionError): processing_permissions.check(db, provider.user_id, novel, provider, 'translation', consent=True)
