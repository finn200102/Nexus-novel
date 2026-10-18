"""No source/network calls: qualify exhaustive, revision-bound metadata RPCs."""
import asyncio
import hashlib
import json
from uuid import UUID, uuid5

import httpx
import pytest

from app.services import metadata_client as client

KEY = '6be0a07b-9d9a-487c-95a7-809684197514'
CAPABILITIES = {'protocols': [1], 'max_page_size': 1000, 'ordering': 'chapter_number,id', 'deletion_authoritative': False}
SOURCE = {'site': 'royalroad', 'story_id': 123, 'source_url': 'https://www.royalroad.com/fiction/123'}


def row(id, number=None):
    return {'id': id, 'chapter_key': str(uuid5(UUID(KEY), str(id))), 'site': 'royalroad', 'story_id': 123,
            'chapter_id': 9223372036854700000 + id, 'chapter_number': number if number is not None else id,
            'title': f'Chapter {id} café', 'url': f'https://www.royalroad.com/fiction/123/chapter/{id}',
            'category': 'story', 'word_count': None, 'identity_kind': 'stable_source_id'}


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode() + b'\n'


def pages(rows, size=1000):
    header = {'protocol': 1, 'novel_id': 123, 'manifest_key': KEY, 'source': SOURCE,
              'identity_kind': 'stable_source_id', 'total': len(rows)}
    fingerprint = hashlib.sha256(encode(header) + b''.join(encode(value) for value in rows)).hexdigest()
    return [{**header, 'revision': 'a' * 64, 'fingerprint': fingerprint, 'complete': True,
             'source_complete': False, 'deletion_authoritative': False,
             'items': rows[start:start+size], 'has_more': start+size < len(rows),
             'next_cursor': str(start+size) if start+size < len(rows) else None}
            for start in range(0, len(rows), size)] or [{**header, 'revision': 'a'*64, 'fingerprint': fingerprint,
             'complete': True, 'source_complete': False, 'deletion_authoritative': False,
             'items': [], 'has_more': False, 'next_cursor': None}]


@pytest.fixture(autouse=True)
def clean_cache():
    client.clear_cache()
    yield
    client.clear_cache()


def transport(monkeypatch, response_pages, capability=None):
    calls = []
    remaining = iter(response_pages)
    async def request(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path == '/chapters/manifest-capabilities':
            value = CAPABILITIES if capability is None else capability
        else:
            value = next(remaining)
            if isinstance(value, BaseException):
                raise value
        return httpx.Response(200, json=value)
    monkeypatch.setattr(client, '_request', request)
    return calls


def test_exhausts_more_than_twenty_thousand_signed_gapped_chapters_and_checks_identity(monkeypatch):
    rows = [row(id, -2147483648 + id*50) for id in range(1, 20006)]
    calls = transport(monkeypatch, pages(rows))
    result = asyncio.run(client.get_chapter_manifest(123))
    assert result.items == rows and result.total == 20005 and len(calls) == 22
    assert result.complete and not result.source_complete and not result.deletion_authoritative
    assert result.source == SOURCE and result.manifest_key == KEY
    assert calls[1][2]['params'] == {'limit': 1000}
    assert calls[2][2]['params'] == {'limit': 1000, 'cursor': '1000', 'revision': 'a'*64}


def test_has_no_twenty_thousand_page_truncation(monkeypatch):
    rows = [row(id) for id in range(1, 20002)]
    calls = transport(monkeypatch, pages(rows, size=1))
    result = asyncio.run(client.get_chapters_from_metadata(123, limit=1))
    assert len(result) == 20001 and result[-1] == rows[-1]
    assert len(calls) == 20002


def test_empty_complete_snapshot_is_cached_and_callers_cannot_mutate_cache(monkeypatch):
    calls = transport(monkeypatch, pages([])*2)
    first = asyncio.run(client.get_chapter_manifest(123))
    first.items.append(row(1)); first.source['site'] = 'changed'
    second = asyncio.run(client.get_chapter_manifest(123))
    assert second.items == [] and second.source == SOURCE and len(calls) == 4


def test_cache_partition_includes_origin_page_size_and_protocol_and_refresh_clears_work(monkeypatch):
    response = pages([row(1)])
    calls = transport(monkeypatch, response*4)
    assert asyncio.run(client.get_chapters_from_metadata(123)) == [row(1)]
    monkeypatch.setattr(client.settings, 'METADATA_SERVER_URL', 'http://other-metadata.invalid')
    assert asyncio.run(client.get_chapters_from_metadata(123)) == [row(1)]
    assert asyncio.run(client.get_chapters_from_metadata(123, limit=1)) == [row(1)]
    client.invalidate_novel_cache(123)
    assert asyncio.run(client.get_chapters_from_metadata(123)) == [row(1)]
    assert len(calls) == 8


@pytest.mark.parametrize('field,value', [('revision','b'*64),('manifest_key','65d8d806-1150-471e-99b3-c953cda21482'),
    ('total',3),('fingerprint','c'*64),('identity_kind','unknown'),('source',{**SOURCE,'story_id':987})])
def test_changed_revision_or_snapshot_metadata_discards_all_pages(monkeypatch, field, value):
    data = pages([row(1),row(2)], size=1); data[1][field] = value
    transport(monkeypatch, data)
    with pytest.raises(client.ChapterManifestError) as caught:
        asyncio.run(client.get_chapter_manifest(123, page_size=1))
    assert caught.value.category == 'manifest_changed'
    assert client.cache._cache == {}


@pytest.mark.parametrize('damage', ['short', 'false_complete', 'duplicate_id', 'duplicate_key', 'duplicate_number',
    'bad_order', 'cycle', 'empty_middle', 'fingerprint', 'future_authority', 'foreign_work', 'bool_number', 'non_integer_source', 'extra_text'])
def test_incomplete_malformed_or_ambiguous_manifests_never_become_cached_lists(monkeypatch, damage):
    data = pages([row(1),row(2),row(3)], size=1)
    if damage == 'short': data[-1]['items'] = []
    elif damage == 'false_complete': data[0]['complete'] = False
    elif damage == 'duplicate_id': data[1]['items'][0]['id'] = 1
    elif damage == 'duplicate_key': data[1]['items'][0]['chapter_key'] = UUID(data[0]['items'][0]['chapter_key']).hex
    elif damage == 'duplicate_number': data[1]['items'][0]['chapter_number'] = 1
    elif damage == 'bad_order': data[1]['items'][0]['chapter_number'] = -1
    elif damage == 'cycle': data[1]['next_cursor'] = data[0]['next_cursor']
    elif damage == 'empty_middle': data[1]['items'] = []
    elif damage == 'fingerprint':
        for page in data: page['fingerprint'] = '0'*64
    elif damage == 'future_authority': data[0]['deletion_authoritative'] = True
    elif damage == 'foreign_work': data[0]['novel_id'] = 456
    elif damage == 'bool_number': data[0]['items'][0]['chapter_number'] = True
    elif damage == 'non_integer_source': data[0]['items'][0]['chapter_id'] = 1.5
    elif damage == 'extra_text': data[0]['items'][0]['content'] = 'Must not belong in a manifest'
    transport(monkeypatch, data)
    with pytest.raises(client.ChapterManifestError): asyncio.run(client.get_chapters_from_metadata(123, limit=1))
    assert client.cache._cache == {}


def test_revision_conflict_has_typed_retry_and_never_uses_legacy_listing(monkeypatch):
    error = httpx.HTTPStatusError('private upstream detail', request=httpx.Request('GET','http://metadata.invalid'),
        response=httpx.Response(409, json={'detail':{'code':'manifest_changed'}}))
    data = pages([row(1), row(2)], size=1)
    calls = transport(monkeypatch, [data[0], error])
    with pytest.raises(client.ChapterManifestError) as caught: asyncio.run(client.get_chapter_manifest(123, page_size=1))
    assert caught.value.retryable and caught.value.category == 'manifest_changed'
    assert 'private upstream' not in str(caught.value)
    assert all(path.endswith('/manifest') or path.endswith('manifest-capabilities') for _,path,_ in calls)
    assert client.cache._cache == {}


@pytest.mark.parametrize('capability', [{**CAPABILITIES,'protocols':[0]}, {**CAPABILITIES,'protocols':[True]}, {}])
def test_explicit_legacy_capability_never_silently_falls_back_to_incomplete_old_route(monkeypatch, capability):
    calls = transport(monkeypatch, [], capability)
    with pytest.raises(client.ChapterManifestError) as caught: asyncio.run(client.get_chapter_manifest(123))
    assert caught.value.category == 'upgrade_required' and len(calls) == 1


def test_unsupported_capability_route_is_actionable_and_not_a_partial_success(monkeypatch):
    async def request(*args, **kwargs):
        raise httpx.HTTPStatusError('missing old route', request=httpx.Request('GET','http://metadata.invalid'),response=httpx.Response(404))
    monkeypatch.setattr(client,'_request',request)
    with pytest.raises(client.ChapterManifestError,match='Upgrade') as caught: asyncio.run(client.get_chapter_manifest(123))
    assert caught.value.category == 'upgrade_required'


def test_explicit_metadata_story_missing_does_not_claim_it_is_an_upgrade_problem(monkeypatch):
    error = httpx.HTTPStatusError('notfound',request=httpx.Request('GET','http://metadata.invalid'),response=httpx.Response(404,json={'detail':{'code':'novel_not_found'}}))
    transport(monkeypatch,[error])
    with pytest.raises(client.ChapterManifestError) as caught: asyncio.run(client.get_chapter_manifest(123))
    assert caught.value.category == 'story_not_found'


def test_record_and_byte_capacity_are_explicit_failures_never_truncation(monkeypatch):
    data = pages([row(1),row(2)])
    monkeypatch.setattr(client,'MAX_MANIFEST_ITEMS',1)
    transport(monkeypatch,data)
    with pytest.raises(client.ChapterManifestError) as caught: asyncio.run(client.get_chapter_manifest(123))
    assert caught.value.category == 'manifest_limit'
    monkeypatch.setattr(client,'MAX_MANIFEST_ITEMS',100)
    monkeypatch.setattr(client,'MAX_MANIFEST_BYTES',1)
    transport(monkeypatch,data)
    with pytest.raises(client.ChapterManifestError) as caught: asyncio.run(client.get_chapter_manifest(123))
    assert caught.value.category == 'manifest_limit' and client.cache._cache == {}


def test_cache_reuse_checks_current_identity_and_revision_before_skipping_later_pages(monkeypatch):
    rows = [row(1),row(2)]
    original = pages(rows, size=1)
    calls = transport(monkeypatch, [*original, original[0]])
    assert asyncio.run(client.get_chapter_manifest(123, page_size=1)).items == rows
    assert asyncio.run(client.get_chapter_manifest(123, page_size=1)).items == rows
    assert len(calls) == 5  # capability+two pages, capability+currentfirstpage
    changed = pages([row(1),row(2),row(3)], size=1)
    for page in changed: page['revision'] = 'd'*64
    calls = transport(monkeypatch, changed)
    assert len(asyncio.run(client.get_chapter_manifest(123, page_size=1)).items) == 3
    assert len(calls) == 4


def test_reused_numeric_story_id_with_new_manifest_identity_cannot_hit_old_cache(monkeypatch):
    original = pages([row(1)])
    transport(monkeypatch, original)
    assert asyncio.run(client.get_chapter_manifest(123)).manifest_key == KEY
    replacement_key = '2da79fee-5704-4d7c-88bc-367a74134ce3'
    replacement = pages([row(2)])
    replacement[0]['manifest_key'] = replacement_key
    header = {key: replacement[0][key] for key in ('protocol','novel_id','manifest_key','source','identity_kind','total')}
    replacement[0]['fingerprint'] = hashlib.sha256(encode(header)+encode(row(2))).hexdigest()
    transport(monkeypatch, replacement)
    result = asyncio.run(client.get_chapter_manifest(123))
    assert result.manifest_key == replacement_key and result.items == [row(2)]


def test_force_refresh_invalidates_every_page_variant_before_complete_refetch(monkeypatch):
    rows = [row(1),row(2)]
    transport(monkeypatch, [*pages(rows,size=1),*pages(rows)])
    asyncio.run(client.get_chapter_manifest(123,page_size=1))
    asyncio.run(client.get_chapter_manifest(123,page_size=1000))
    assert len(client.cache._cache) == 2
    calls = transport(monkeypatch,pages(rows,size=1))
    assert asyncio.run(client.get_chapters_from_metadata(123,limit=1,force_refresh=True)) == rows
    assert len(calls) == 3 and len(client.cache._cache) == 1


@pytest.mark.parametrize('status,code,category', [(422,'manifest_capacity','manifest_limit'),
    (503,'manifest_not_ready','upgrade_required'),(422,'invalid_manifest_cursor','manifest_invalid')])
def test_structured_manifest_failures_keep_actionable_category_without_upstream_body(monkeypatch,status,code,category):
    error = httpx.HTTPStatusError('SECRET upstream URL',request=httpx.Request('GET','http://metadata.invalid'),
        response=httpx.Response(status,json={'detail':{'code':code,'message':'SECRET raw source'}}))
    transport(monkeypatch,[error])
    with pytest.raises(client.ChapterManifestError) as caught: asyncio.run(client.get_chapter_manifest(123))
    assert caught.value.category==category and not caught.value.retryable
    assert 'SECRET' not in str(caught.value) and client.cache._cache=={}


def test_unknown_source_header_is_truthful_and_does_not_invent_stable_identity(monkeypatch):
    data=pages([])
    data[0]['source']={'site':None,'story_id':None,'source_url':'https://example.org/original'}
    data[0]['identity_kind']='unknown'
    header={key:data[0][key] for key in ('protocol','novel_id','manifest_key','source','identity_kind','total')}
    data[0]['fingerprint']=hashlib.sha256(encode(header)).hexdigest()
    transport(monkeypatch,data)
    result=asyncio.run(client.get_chapter_manifest(123))
    assert result.identity_kind=='unknown' and result.source['story_id'] is None


def test_refresh_invalidates_all_complete_manifest_variants_before_source_refresh(monkeypatch):
    transport(monkeypatch,pages([row(1)]))
    asyncio.run(client.get_chapter_manifest(123))
    assert client.cache._cache
    async def refresh(method,path,**kwargs):
        assert method=='PUT' and path=='/novels/123'
        assert not any(key.startswith(client._manifest_cache_prefix(123)) for key in client.cache._cache)
        return httpx.Response(200,json={'id':123})
    monkeypatch.setattr(client,'_request',refresh)
    assert asyncio.run(client.refresh_novel_metadata(123))=={'id':123}
