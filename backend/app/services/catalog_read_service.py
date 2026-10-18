"""Reader-safe catalog failures without leaking transport details or secrets."""
import httpx
from fastapi import HTTPException
from app.services import metadata_client


def unavailable(exc):
    cause = exc.__cause__
    if isinstance(cause, httpx.HTTPStatusError):
        status = cause.response.status_code
        if status == 404:
            raise HTTPException(404, detail='Catalog record is unavailable') from exc
        if status in (409, 422):
            raise HTTPException(status, detail={'code':'catalog_criteria_changed',
                'message':'These catalog criteria are unavailable. Review your selection and search again.'}) from exc
    raise HTTPException(503, detail={'code':'catalog_unavailable',
        'message':'The catalog is temporarily unavailable. Try again shortly.'}) from exc


async def request(path, **kwargs):
    try:
        response = await metadata_client._request('GET', path, timeout=metadata_client.INTERACTIVE_TIMEOUT, **kwargs)
        return response.json()
    except (RuntimeError, ValueError, TypeError) as exc:
        unavailable(exc)


async def list_novels(**kwargs):
    try:
        return await metadata_client.list_novels_metadata(**kwargs)
    except (RuntimeError, ValueError, TypeError) as exc:
        unavailable(exc)
