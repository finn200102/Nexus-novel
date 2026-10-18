"""Read one immutable, exhaustive source observation with explicit authority.

The database manifest remains a compatibility view. It cannot replace a raw or
changed source capture, and observed absence never becomes deletion permission
unless the service supplies audited source IDs or an explicit reviewed mapping.
"""
import hashlib
import json
import re
from datetime import datetime

from app.services import metadata_client as client

_HEAD = {'protocol', 'novel_id', 'manifest_key', 'revision', 'source', 'capture'}
_SUMMARY = {'id', 'captured_at', 'fingerprint', 'total', 'source_complete',
            'deletion_authoritative', 'authority_kind', 'review_id'}
_PAGE = {'protocol', 'novel_id', 'capture_id', 'manifest_key', 'revision', 'source',
         'fingerprint', 'total', 'items', 'next_cursor', 'has_more', 'complete',
         'source_complete', 'deletion_authoritative', 'authority_kind', 'review_id'}
_LINEAGE = {'protocol','novel_id','capture_id','manifest_key','revision','source','fingerprint',
            'review_id','lineage_fingerprint','total','items','offset','limit','has_more','next_offset'}


def _invalid(message):
    client._manifest_invalid(message)


def _source(value):
    if (not isinstance(value, dict) or set(value) != {'site', 'story_id', 'source_url'}
            or (value['site'] is not None and (not isinstance(value['site'], str) or not 1 <= len(value['site']) <= 64))
            or (value['story_id'] is not None and not client._manifest_integer(value['story_id'], -(2**63), 2**63-1))
            or (value['source_url'] is not None and (not isinstance(value['source_url'], str) or len(value['source_url']) > 10000))):
        _invalid('Metadata returned an invalid source capture namespace')


def _head(value, novel_id):
    if (not isinstance(value, dict) or set(value) != _HEAD or type(value['protocol']) is not int
            or value['protocol'] != 1 or type(value['novel_id']) is not int or value['novel_id'] != novel_id):
        _invalid('Metadata returned an invalid source capture header')
    client._manifest_uuid(value['manifest_key'])
    if not isinstance(value['revision'], str) or not re.fullmatch('[0-9a-f]{64}', value['revision']):
        _invalid('Metadata returned an invalid source capture revision')
    _source(value['source'])
    summary = value['capture']
    if summary is None:
        return
    if not isinstance(summary, dict) or set(summary) != _SUMMARY:
        _invalid('Metadata returned an invalid source capture summary')
    client._manifest_uuid(summary['id'])
    if not isinstance(summary['fingerprint'], str) or not re.fullmatch('[0-9a-f]{64}', summary['fingerprint']):
        _invalid('Metadata returned an invalid source capture fingerprint')
    if not client._manifest_integer(summary['total'], 0, client.MAX_MANIFEST_ITEMS):
        raise client.ChapterManifestError('manifest_limit', 'The source capture exceeds the supported chapter bound')
    if any(type(summary[key]) is not bool for key in ('source_complete', 'deletion_authoritative')):
        _invalid('Metadata returned invalid source capture authority')
    if not isinstance(summary['authority_kind'], str) or summary['authority_kind'] not in {'adapter_stable', 'raw_observation', 'reviewed_mapping'}:
        _invalid('Metadata returned an unknown source capture authority')
    if summary['authority_kind'] == 'reviewed_mapping':
        client._manifest_uuid(summary['review_id'])
    elif summary['review_id'] is not None:
        _invalid('An unreviewed source capture claimed a review identity')
    timestamp = summary['captured_at']
    try:
        if not isinstance(timestamp, str) or not 1 <= len(timestamp) <= 64:
            raise ValueError()
        parsed = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError()
    except ValueError:
        _invalid('Metadata returned an invalid source capture date')


async def read_source_capture(novel_id, *, page_size):
    """Return an accepted snapshot, or None when this peer has no capture.

    A declared but incomplete/unreviewed capture is an actionable error. A stale
    page, missing route or digest mismatch never falls back to an older list.
    No cache shortcuts skip checking every captured item and the final head.
    """
    path = f'/chapters/novel/{novel_id}/source-manifest-head'
    head = await client._manifest_request(path)
    _head(head, novel_id)
    summary = head['capture']
    if summary is None:
        return None
    if summary['authority_kind'] == 'raw_observation':
        raise client.ChapterManifestError('source_review_required',
            'The source chapter list needs administrator review before it can be linked to your reading. Existing chapters are preserved.')
    if not summary['source_complete'] or not summary['deletion_authoritative']:
        _invalid('Metadata has not established complete, accepted source membership')
    invariant = {key: head[key] for key in ('protocol', 'novel_id', 'manifest_key', 'revision', 'source')}
    invariant.update({key: summary[key] for key in ('fingerprint', 'total', 'source_complete',
                     'deletion_authoritative', 'authority_kind', 'review_id')})
    invariant['capture_id'] = summary['id']
    rows, ids, keys, numbers, external, cursors = [], set(), set(), set(), set(), set()
    cursor = None
    byte_count = 2
    digest = hashlib.sha256(b'[')
    while True:
        params = {'revision': head['revision'], 'limit': page_size}
        if cursor is not None:
            params['cursor'] = cursor
        page = await client._manifest_request(
            f'/chapters/novel/{novel_id}/source-manifest-captures/{summary["id"]}', **params)
        if not isinstance(page, dict) or set(page) != _PAGE:
            _invalid('Metadata returned an invalid source capture page')
        _source(page['source'])
        if any(page[key] != value or type(page[key]) is not type(value) for key, value in invariant.items()):
            raise client.ChapterManifestError('manifest_changed',
                'The source capture changed while loading. Refresh and review the chapter list.', retryable=True)
        if page['complete'] is not True or type(page['has_more']) is not bool:
            _invalid('Metadata did not provide a complete source capture page')
        batch = page['items']
        if not isinstance(batch, list) or len(batch) > page_size or len(rows) + len(batch) > summary['total']:
            _invalid('Metadata returned inconsistent source capture counts')
        for item in batch:
            client._manifest_item(item, novel_id)
            key = client._manifest_uuid(item['chapter_key'])
            if item['site'] != head['source']['site'] or item['story_id'] != head['source']['story_id']:
                _invalid('A source capture chapter belongs to another namespace')
            if summary['authority_kind'] == 'adapter_stable' and item['identity_kind'] != 'stable_source_id':
                _invalid('An adapter capture contains an unproved positional identity')
            if item['id'] in ids or key in keys or item['chapter_number'] in numbers:
                _invalid('Metadata returned duplicate source capture identities')
            if item['identity_kind'] == 'stable_source_id' and item['chapter_id'] in external:
                _invalid('Metadata returned ambiguous stable source chapter identities')
            if rows and (item['chapter_number'], item['id']) <= (rows[-1]['chapter_number'], rows[-1]['id']):
                _invalid('Metadata returned source chapters outside their declared order')
            packed = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
            byte_count += len(packed) + bool(rows)
            if byte_count > min(client.MAX_MANIFEST_BYTES, 64 * 1024**2):
                raise client.ChapterManifestError('manifest_limit', 'The source capture exceeds its metadata byte budget')
            if rows:
                digest.update(b',')
            digest.update(packed)
            rows.append(item)
            ids.add(item['id']); keys.add(key); numbers.add(item['chapter_number'])
            if item['identity_kind'] == 'stable_source_id':
                external.add(item['chapter_id'])
        next_cursor = page['next_cursor']
        if not page['has_more']:
            if next_cursor is not None or len(rows) != summary['total']:
                _invalid('Metadata ended a source capture before its declared total')
            break
        if (not batch or not isinstance(next_cursor, str) or not 1 <= len(next_cursor) <= 2048
                or next_cursor in cursors or len(rows) >= summary['total']):
            _invalid('Metadata returned an invalid or repeated source capture cursor')
        cursors.add(next_cursor)
        cursor = next_cursor
    digest.update(b']')
    if digest.hexdigest() != summary['fingerprint']:
        _invalid('The complete source capture does not match its fingerprint')
    lineage, lineage_fingerprint = (await _lineage(novel_id, head, rows, page_size)
        if summary['authority_kind'] == 'reviewed_mapping' else ([], None))
    current = await client._manifest_request(path)
    _head(current, novel_id)
    if current != head:
        raise client.ChapterManifestError('manifest_changed',
            'The source changed before its complete capture could be accepted. Retry the chapter list.', retryable=True)
    kinds = {row['identity_kind'] for row in rows}
    identity_kind = next(iter(kinds)) if len(kinds) == 1 else ('stable_source_id' if not rows and summary['authority_kind'] == 'adapter_stable' else 'unknown')
    return client.ChapterManifestSnapshot(novel_id=novel_id, manifest_key=head['manifest_key'],
        revision=head['revision'], fingerprint=summary['fingerprint'], total=summary['total'],
        source=head['source'], items=rows, identity_kind=identity_kind, source_complete=True,
        deletion_authoritative=True, source_capture_id=summary['id'],
        source_authority_kind=summary['authority_kind'], source_review_id=summary['review_id'],
        source_lineage=lineage, source_lineage_fingerprint=lineage_fingerprint)


async def _lineage(novel_id, head, chapters, page_size):
    """Verify advisory old-to-new associations, without granting reading proof."""
    summary=head['capture']
    invariant={key:head[key] for key in ('protocol','novel_id','manifest_key','revision','source')}
    invariant.update(capture_id=summary['id'],fingerprint=summary['fingerprint'],
        review_id=summary['review_id'],total=summary['total'])
    rows=[];old_keys=set();new_keys=set();fingerprint=None;size=2
    digest=hashlib.sha256(b'[')
    while True:
        offset=len(rows)
        page=await client._manifest_request(
            f'/chapters/novel/{novel_id}/source-manifest-captures/{summary["id"]}/lineage',
            expected_manifest_key=head['manifest_key'],revision=head['revision'],offset=offset,limit=page_size)
        if not isinstance(page,dict) or set(page)!=_LINEAGE:
            _invalid('Metadata returned an invalid reviewed source lineage page')
        _source(page['source'])
        if any(page[key]!=value or type(page[key]) is not type(value) for key,value in invariant.items()):
            raise client.ChapterManifestError('manifest_changed','The reviewed chapter associations changed. Refresh the source list.',retryable=True)
        value=page['lineage_fingerprint']
        if not isinstance(value,str) or not re.fullmatch('[0-9a-f]{64}',value):
            _invalid('Metadata returned an invalid chapter lineage fingerprint')
        if fingerprint is None:fingerprint=value
        elif value!=fingerprint:
            raise client.ChapterManifestError('manifest_changed','The reviewed chapter associations changed between pages.',retryable=True)
        if (type(page['offset']) is not int or page['offset']!=offset or type(page['limit']) is not int
                or page['limit']!=page_size or type(page['has_more']) is not bool):
            _invalid('Metadata returned invalid chapter lineage paging')
        batch=page['items']
        if not isinstance(batch,list) or len(batch)>page_size or offset+len(batch)>summary['total']:
            _invalid('Metadata returned inconsistent chapter lineage counts')
        for item in batch:
            ordinal=len(rows)
            if (not isinstance(item,dict) or set(item)!={'capture_ordinal','old_chapter_key','new_chapter_key'}
                    or type(item['capture_ordinal']) is not int or item['capture_ordinal']!=ordinal):
                _invalid('Metadata returned incomplete or unordered chapter lineage')
            new_key=client._manifest_uuid(item['new_chapter_key'])
            old_key=client._manifest_uuid(item['old_chapter_key']) if item['old_chapter_key'] is not None else None
            if (new_key!=client._manifest_uuid(chapters[ordinal]['chapter_key']) or new_key in new_keys
                    or (old_key is not None and old_key in old_keys)):
                _invalid('Metadata returned ambiguous or foreign chapter lineage')
            packed=json.dumps(item,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
            size+=len(packed)+bool(rows)
            if size>min(client.MAX_MANIFEST_BYTES,64*1024**2):
                raise client.ChapterManifestError('manifest_limit','The reviewed chapter associations exceed their metadata budget')
            if rows:digest.update(b',')
            digest.update(packed);rows.append(item);new_keys.add(new_key)
            if old_key is not None:old_keys.add(old_key)
        if not page['has_more']:
            if page['next_offset'] is not None or len(rows)!=summary['total']:
                _invalid('Metadata ended the reviewed chapter associations before their declared total')
            break
        if (not batch or len(rows)>=summary['total'] or type(page['next_offset']) is not int
                or page['next_offset']!=len(rows)):
            _invalid('Metadata returned invalid chapter lineage continuation')
    digest.update(b']')
    if digest.hexdigest()!=fingerprint:
        _invalid('The reviewed chapter associations do not match their fingerprint')
    return rows,fingerprint
