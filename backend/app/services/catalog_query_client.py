"""Internal prepared catalog reads, with safe typed failure categories."""
import httpx
from fastapi import HTTPException
from app.services import metadata_client

async def request(action: str, payload: dict) -> dict:
    if action not in {'prepare', 'results', 'baseline', 'events'}:
        raise ValueError('Unsupported catalog query operation')
    try:
        response = await metadata_client._request('POST', f'/internal/catalog-queries/{action}',
            timeout=metadata_client.BACKGROUND_TIMEOUT, json=payload)
        result = response.json()
    except RuntimeError as exc:
        cause = exc.__cause__
        if isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code in (409, 422):
            raise HTTPException(409, detail={'code': 'catalog_query_review_required',
                'message': 'The catalog query is no longer available with these settings. Prepare and review it again.'}) from exc
        raise HTTPException(503, detail={'code': 'catalog_query_unavailable',
            'message': 'The catalog is temporarily unavailable. Your saved query and matches are retained.'}) from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(503, detail={'code': 'catalog_query_unavailable', 'message': 'The catalog returned an invalid response.'}) from exc
    if not isinstance(result, dict):
        raise HTTPException(503, 'The catalog returned an invalid response')
    return result
