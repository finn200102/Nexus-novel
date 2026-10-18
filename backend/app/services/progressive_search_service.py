"""Independent, account-fenced catalog and source pages for progressive search."""
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.models.user import User
from app.routers.catalog_editions import snapshot
from app.schemas.live_search import LiveCapabilitiesResponse, LiveSearchResult
from app.services import catalog_query_client, metadata_client
from app.services.blocklist_service import apply_blocklist


ERROR_CODES = {'unsupported', 'invalid_query', 'source_failed', 'unknown', 'rate_limited',
               'circuit_open', 'source_blocked', 'timeout', 'metadata_unavailable',
               'prohibited_host', 'input_limit', 'output_limit', 'execution_limit',
               'source_policy', 'redirect_limit', 'malformed', 'source_version_changed',
               'plugin_disabled', 'source_unavailable', 'source_changed', 'unsupported_operation',
               'invalid_template', 'robots_disallowed', 'budget_exhausted'}


def valid_rows(rows):
    try:
        return [LiveSearchResult.model_validate(row).model_dump() for row in rows]
    except (ValidationError, TypeError, ValueError) as exc:
        raise HTTPException(503, detail='The source returned an invalid page') from exc


def query(value):
    value = value.strip()
    if not value:
        raise HTTPException(422, detail='Enter a search term')
    return value


async def begin(db, auth):
    ids = (auth.user.id, auth.session.id)
    proof = await run_in_threadpool(snapshot, db, *ids)
    return (*ids, proof)


def finish(db, context, items=None):
    user_id, session_id, proof = context
    if snapshot(db, user_id, session_id) != proof:
        raise HTTPException(409, detail={'code': 'catalog_visibility_changed',
            'message': 'Your content rules changed. Search again.'})
    try:
        return apply_blocklist(db, db.get(User, user_id), items) if items is not None else None
    finally:
        db.rollback()


async def checked(db, context, items=None):
    return await run_in_threadpool(finish, db, context, items)


async def capabilities(db, context):
    raw = await metadata_client.live_capabilities()
    await checked(db, context)
    try:
        return LiveCapabilitiesResponse.model_validate(raw)
    except (ValidationError, TypeError, ValueError) as exc:
        raise HTTPException(503, detail='Source capabilities are temporarily unavailable') from exc


async def local(db, context, q, page, limit):
    # Explicit lexical preparation never invokes a model, source, or crawler.
    prepared = await catalog_query_client.request('prepare', {
        'definition': {'q': query(q)}, 'mode': 'lexical', 'visibility': context[2][2],
    })
    await checked(db, context)
    if not isinstance(prepared.get('prepared'), dict):
        raise HTTPException(503, detail='The catalog returned an invalid query')
    result = await catalog_query_client.request('results', {
        'prepared': prepared['prepared'], 'offset': (page - 1) * limit, 'limit': limit,
    })
    if not isinstance(result.get('has_more'), bool):
        raise HTTPException(503, detail='The catalog returned invalid pagination')
    if not isinstance(result.get('items'), list) or len(result['items']) > limit or any(not isinstance(row, dict) for row in result['items']):
        raise HTTPException(503, detail='The catalog returned an invalid page')
    rows = [{**row, 'metadata_id': row.get('id'), 'url': row.get('source_url'),
             'sources': ['local']} for row in result['items']]
    return {'page': page, 'results': await checked(db, context, valid_rows(rows)), 'errors': [],
            'has_more': result['has_more']}


async def source(db, context, source_id, q, page, pinned_digest=None, *, feed=None):
    available = await capabilities(db, context)
    selected = next((item for item in available.sources if item.source_id == source_id), None)
    if selected is None or (feed is None and not selected.search):
        raise HTTPException(422, detail='Choose an available searchable source')
    if feed is not None and feed.split(':', 1)[0] not in selected.browse_feeds:
        raise HTTPException(422, detail='Choose an available source feed')
    if pinned_digest is not None and selected.digest != pinned_digest:
        raise HTTPException(409, detail={'code': 'source_version_changed',
            'message': 'This source package changed. Reload sources and review your selection.'})
    params = {'site': source_id, 'page': page}
    if feed is None:
        params['q'] = query(q)
    else:
        params['feed'] = feed
    # Pin the selected package even if a legacy caller omitted its pin, so a
    # concurrent admin update cannot substitute another parser after review.
    if selected.digest:
        params['pinned_digest'] = selected.digest
    answer = await metadata_client.live_listing('live' if feed is None else 'browse', params)
    return await page_from_answer(db, context, source_id, page, answer)


async def page_from_answer(db, context, source_id, page, answer):
    if not isinstance(answer, dict):
        raise HTTPException(503, detail='The source returned an invalid page')
    raw = answer.get('results')
    if raw is None:
        raw = []
    if not isinstance(raw, list) or len(raw) > 1000 or any(not isinstance(item, dict) for item in raw):
        raise HTTPException(503, detail='The source returned an invalid page')
    if any(item.get('source_id') is not None and item.get('source_id') != source_id for item in raw):
        raise HTTPException(503, detail='The source returned an inconsistent identity')
    rows = [{**item, 'id': item.get('metadata_id'), 'source_url': item.get('url'),
             'source_id': source_id, 'sources': ['live']} for item in raw]
    rows = await checked(db, context, valid_rows(rows))
    error = answer.get('error')
    if error is not None and not isinstance(error, dict):
        raise HTTPException(503, detail='The source returned an invalid page')
    code = error.get('code') if error else None
    # Never expose upstream transport exception strings or configured endpoints.
    errors = [] if not error else [{
        'site': source_id, 'code': code if isinstance(code, str) and code in ERROR_CODES else 'source_failed',
        'message': 'This source could not complete the request. Try again later.',
        'retryable': error.get('retryable') if isinstance(error.get('retryable'), bool) else None,
    }]
    more = answer.get('has_more')
    return {'source_id': source_id, 'page': page, 'results': rows, 'errors': errors,
            'has_more': more if isinstance(more, bool) else None}
