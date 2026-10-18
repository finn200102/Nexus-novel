"""Independent source pages cannot leak stale accounts or hidden source facts."""
from datetime import datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.orm import Session

from app.models.account import UserSession
from app.models.blocklist import BlocklistEntry
from app.models.user import User

DIGEST = 'a' * 64


def capability_response():
    sources = [dict(source_id=site, site=site, name=site, kind='builtin', search=True,
                    browse_feeds=['rising-stars'], user_lists=[], plugin_id=None,
                    version=None, digest=None, limitations=[])
               for site in ['royalroad', 'fanfiction', 'archive']]
    sources.append(dict(source_id='plugin-fixture', site='webserial', name='Private serial source',
                        kind='plugin', search=True, browse_feeds=['latest'], user_lists=[],
                        plugin_id='fixture', version='1.0.0', digest=DIGEST, limitations=['Public pages only']))
    return dict(search=[item['source_id'] for item in sources], browse={}, user_lists={}, sources=sources, sources_limited=False)


def hit(**extra):
    return dict(metadata_id=None, url='https://fixture.invalid/Work/1', title='Allowed story',
                author='Writer', description='Public summary', site='webserial', source_id='plugin-fixture',
                tags=[], genres=[], fandoms=[], content_rating='general', **extra)


@pytest.fixture
def upstream(monkeypatch):
    caps = AsyncMock(return_value=capability_response())
    listing = AsyncMock(return_value={'results': [hit()], 'error': None, 'has_more': None})
    monkeypatch.setattr('app.services.metadata_client.live_capabilities', caps)
    monkeypatch.setattr('app.services.metadata_client.live_listing', listing)
    return caps, listing


def test_source_is_one_page_pinned_distinct_from_persisted_site(client, auth_headers, upstream):
    response = client.get('/discovery/live/source', params={'source_id': 'plugin-fixture', 'q': 'Story', 'page': 7}, headers=auth_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['source_id'] == 'plugin-fixture' and body['has_more'] is None
    assert body['results'][0]['metadata_id'] is None and body['results'][0]['site'] == 'webserial'
    upstream[1].assert_awaited_once_with('live', {'site': 'plugin-fixture', 'q': 'Story', 'page': 7, 'pinned_digest': DIGEST})
    assert response.headers['cache-control'] == 'private, no-store'


@pytest.mark.parametrize('params', [
    {'source_id': 'plugin-fixture', 'q': 'x', 'page': 51},
    {'source_id': 'plugin-fixture', 'q': 'x' * 201},
    {'source_id': 'plugin-fixture', 'q': '  '},
    {'source_id': '../secret', 'q': 'x'},
    {'source_id': 'plugin-fixture', 'q': 'x', 'pinned_digest': 'invalid'},
])
def test_request_bounds_reject_without_any_upstream(client, auth_headers, upstream, params):
    assert client.get('/discovery/live/source', params=params, headers=auth_headers).status_code == 422
    upstream[0].assert_not_awaited()
    upstream[1].assert_not_awaited()


def test_unknown_or_changed_source_rejected_before_source_fetch(client, auth_headers, upstream):
    for source, pin, status in [('unknown', None, 422), ('plugin-fixture', 'b' * 64, 409)]:
        params = {'source_id': source, 'q': 'x'}
        if pin: params['pinned_digest'] = pin
        assert client.get('/discovery/live/source', params=params, headers=auth_headers).status_code == status
    upstream[1].assert_not_awaited()


def test_browse_alias_and_capability_validation(client, auth_headers, upstream):
    response = client.get('/discovery/live/browse?source_id=plugin-fixture&feed=latest&page=2', headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()['feed'] == 'latest'
    upstream[1].assert_awaited_once_with('browse', {'site': 'plugin-fixture', 'feed': 'latest', 'page': 2, 'pinned_digest': DIGEST})
    upstream[1].reset_mock()
    for query in ['source_id=plugin-fixture&feed=unlisted', 'source_id=plugin-fixture&site=archive&feed=latest']:
        assert client.get('/discovery/live/browse?' + query, headers=auth_headers).status_code == 422
    upstream[1].assert_not_awaited()


@pytest.mark.parametrize('kind,field,value', [
    ('tag', 'tags', ['Hidden']), ('genre', 'genres', ['Hidden']),
    ('fandom', 'fandoms', ['Hidden']), ('author', 'author', 'Hidden'),
    ('word', 'description', 'Contains Hidden material'),
])
def test_complete_personal_rules_filter_source_results(client, db, test_user, auth_headers, upstream, kind, field, value):
    db.add(BlocklistEntry(user_id=test_user.id, kind=kind, value='Hidden')); db.commit()
    row = hit(); row[field] = value
    upstream[1].return_value = {'results': [row], 'error': None}
    response = client.get('/discovery/live/source?source_id=plugin-fixture&q=x', headers=auth_headers)
    assert response.status_code == 200 and response.json()['results'] == []


@pytest.mark.parametrize('phase', ['capabilities', 'results'])
@pytest.mark.parametrize('change,status', [('rules', 409), ('disabled', 403), ('signout', 401)])
def test_changes_during_wait_are_authoritatively_fenced(client, db, test_user, auth_headers, upstream, phase, change, status):
    user_id = test_user.id
    async def alter():
        assert not db.in_transaction()
        with Session(db.get_bind()) as other:
            if change == 'rules': other.add(BlocklistEntry(user_id=user_id, kind='word', value='New exclusion'))
            elif change == 'disabled': other.query(User).filter_by(id=user_id).update({'is_disabled': True})
            else: other.query(UserSession).filter_by(user_id=user_id).update({'revoked_at': datetime.now()})
            other.commit()
    async def capabilities():
        if phase == 'capabilities': await alter()
        return capability_response()
    async def source_response(*args, **kwargs):
        if phase == 'results': await alter()
        row = hit(); row['title'] = 'PRIVATE RESPONSE'
        return {'results': [row], 'error': None}
    upstream[0].side_effect = capabilities
    upstream[1].side_effect = source_response
    response = client.get('/discovery/live/source?source_id=plugin-fixture&q=x', headers=auth_headers)
    assert response.status_code == status, response.text
    assert 'PRIVATE RESPONSE' not in response.text
    if phase == 'capabilities': upstream[1].assert_not_awaited()


def test_local_is_lexical_prefiltered_and_independent_of_source_capabilities(client, db, test_user, auth_headers, upstream, monkeypatch):
    db.add(BlocklistEntry(user_id=test_user.id, kind='fandom', value='Forbidden')); db.commit()
    calls = []
    async def catalog(action, payload):
        assert not db.in_transaction()
        calls.append((action, payload))
        if action == 'prepare':
            assert payload['mode'] == 'lexical' and payload['definition'] == {'q': 'Local text'}
            assert payload['visibility']['exclude_fandom'] == ['Forbidden']
            return {'prepared': {'signed': 'fixture'}}
        assert payload == {'prepared': {'signed': 'fixture'}, 'offset': 40, 'limit': 20}
        return {'items': [{'id': 7, 'source_url': 'https://fixture.invalid/7', 'title': 'Local'}], 'has_more': True}
    monkeypatch.setattr('app.services.catalog_query_client.request', catalog)
    response = client.get('/discovery/live/local?q=Local%20text&page=3', headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.json()['has_more'] is True and response.json()['results'][0]['metadata_id'] == 7
    assert [call[0] for call in calls] == ['prepare', 'results']
    upstream[0].assert_not_awaited(); upstream[1].assert_not_awaited()


def test_errors_are_sanitized_and_unknown_end_remains_unknown(client, auth_headers, upstream):
    upstream[1].return_value = {'error': {'code': 'timeout', 'message': 'SECRET credential https://internal.invalid', 'retryable': True}}
    response = client.get('/discovery/live/source?source_id=plugin-fixture&q=x', headers=auth_headers)
    assert response.status_code == 200 and response.json()['has_more'] is None
    assert response.json()['errors'][0]['retryable'] is True
    assert 'SECRET' not in response.text and 'internal.invalid' not in response.text


def test_aggregate_rejects_unbounded_or_unsupported_fanout(client, auth_headers, upstream):
    for sites in [['unknown'], ['royalroad'] * 101]:
        response = client.get('/discovery/live', params={'q': 'x', 'sites': sites}, headers=auth_headers)
        assert response.status_code == 422
    upstream[1].assert_not_awaited()


def test_openapi_response_contracts_are_named(client):
    spec = client.get('/openapi.json').json()
    for path, name in [('/discovery/live/local', 'LiveSearchPage'), ('/discovery/live/source', 'LiveSourcePage'), ('/discovery/live/capabilities', 'LiveCapabilitiesResponse')]:
        assert spec['paths'][path]['get']['responses']['200']['content']['application/json']['schema']['$ref'].endswith('/' + name)


@pytest.mark.parametrize('phase', ['prepare', 'results'])
def test_local_stops_after_permission_change_without_source_calls(client, db, test_user, auth_headers, upstream, monkeypatch, phase):
    user_id = test_user.id
    calls = []
    async def catalog(action, payload):
        assert not db.in_transaction()
        calls.append(action)
        if action == phase:
            with Session(db.get_bind()) as other:
                other.add(BlocklistEntry(user_id=user_id, kind='fandom', value='Newly forbidden'))
                other.commit()
        if action == 'prepare': return {'prepared': {'signed': True}}
        return {'items': [{'id': 1, 'title': 'PRIVATE RESULT', 'source_url': 'https://fixture.invalid/1'}], 'has_more': False}
    monkeypatch.setattr('app.services.catalog_query_client.request', catalog)
    response = client.get('/discovery/live/local?q=x', headers=auth_headers)
    assert response.status_code == 409 and 'PRIVATE RESULT' not in response.text
    assert calls == (['prepare'] if phase == 'prepare' else ['prepare', 'results'])
    upstream[0].assert_not_awaited(); upstream[1].assert_not_awaited()


def test_live_routes_require_auth_before_any_upstream(client, upstream):
    for path in ['/discovery/live/capabilities', '/discovery/live/local?q=x',
                 '/discovery/live/source?source_id=plugin-fixture&q=x', '/discovery/live/browse?site=royalroad&feed=rising-stars']:
        assert client.get(path).status_code == 401
    upstream[0].assert_not_awaited(); upstream[1].assert_not_awaited()


def test_personal_rating_limit_applies_to_live_unknown_and_explicit(client, db, test_user, auth_headers, upstream):
    test_user.max_content_rating = 'general'; test_user.hide_unrated = True; db.commit()
    unknown = hit(); unknown['content_rating'] = None
    adult = hit(); adult['content_rating'] = 'explicit'
    upstream[1].return_value = {'results': [unknown, adult, hit()], 'error': None, 'has_more': False}
    response = client.get('/discovery/live/source?source_id=plugin-fixture&q=x', headers=auth_headers)
    assert response.status_code == 200 and len(response.json()['results']) == 1
    assert response.json()['has_more'] is False


@pytest.mark.parametrize('payload', [
    {'results': ['not a story']}, {'results': 0}, {'error': []},
    {'results': [{'metadata_id': 1, 'title': 'Invalid URL', 'url': 'javascript:alert(1)'}]},
    {'results': [{'metadata_id': True, 'title': 'Invalid ID', 'url': 'https://fixture.invalid/x'}]},
    {'results': [{'metadata_id': 1, 'url': 'https://fixture.invalid/x'}]},
    {'results': [{'metadata_id': 1, 'title': 'Wrong identity', 'url': 'https://fixture.invalid/x', 'source_id': []}]},
])
def test_replacing_source_payload_with_bad_shape_is_safe(client, auth_headers, upstream, payload):
    upstream[1].return_value = payload
    # Invalid upstream shape is rejected at the server boundary, never exposed.
    response = client.get('/discovery/live/source?source_id=plugin-fixture&q=x', headers=auth_headers)
    assert response.status_code == 503


def test_untrusted_error_code_cannot_leak_transport_text(client, auth_headers, upstream):
    for code in ['secret-private-url', ['invalid shape']]:
        upstream[1].return_value = {'error': {'code': code, 'message': 'private'}}
        response = client.get('/discovery/live/source?source_id=plugin-fixture&q=x', headers=auth_headers)
        assert response.status_code == 200 and response.json()['errors'][0]['code'] == 'source_failed'
        assert 'secret-private-url' not in response.text


def test_url_dedup_preserves_case_sensitive_source_paths():
    from app.routers.discovery import _url_key
    assert _url_key('http://EXAMPLE.org/Work/1/#reader') == _url_key('https://example.org/Work/1')
    assert _url_key('https://example.org/Work/1') != _url_key('https://example.org/work/1')


def test_metadata_transport_invalid_json_becomes_safe_site_error(monkeypatch):
    import asyncio
    from app.services import metadata_client
    class InvalidResponse:
        def json(self): raise ValueError('PRIVATE invalid upstream document')
    monkeypatch.setattr(metadata_client, '_request', AsyncMock(return_value=InvalidResponse()))
    result = asyncio.run(metadata_client.live_listing('live', {'site': 'royalroad', 'page': 1}))
    assert result['results'] == [] and result['error']['code'] == 'metadata_unavailable'
    assert 'PRIVATE' not in str(result)


def test_malformed_capabilities_are_safe_and_do_not_dispatch(client, auth_headers, upstream):
    upstream[0].return_value = {'sources': 'PRIVATE malformed response'}
    response = client.get('/discovery/live/source?source_id=plugin-fixture&q=x', headers=auth_headers)
    assert response.status_code == 503 and 'PRIVATE' not in response.text
    upstream[1].assert_not_awaited()
