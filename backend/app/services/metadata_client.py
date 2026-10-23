import asyncio
import os
import httpx
import time
import json
from typing import Optional, Any
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from config.settings import settings
from app.logging_config import get_logger, get_request_id, redact_url

logger = get_logger("metadata_client")

CACHE_TTL = 300
CACHE_MAX_ENTRIES = 512
INTERACTIVE_TIMEOUT = httpx.Timeout(15.0, connect=3.0)
BACKGROUND_TIMEOUT = httpx.Timeout(20.0, connect=3.0)
try:
    _chapter_timeout = max(20, min(300, int(os.getenv("NEXUS_CHAPTER_DOWNLOAD_TIMEOUT", "180"))))
except ValueError:
    _chapter_timeout = 180
CHAPTER_FETCH_TIMEOUT = httpx.Timeout(_chapter_timeout, connect=3.0)
# Live site listings may queue behind the shared per-site limiter.
LIVE_LISTING_TIMEOUT = httpx.Timeout(45.0, connect=3.0)


@dataclass
class CacheEntry:
    data: Any
    expires_at: float


class ChapterSourceError(RuntimeError):
    """Typed error returned by Nexus Server's public-chapter contract."""

    def __init__(self, category: str, message: str, *, retryable: bool):
        super().__init__(message)
        self.category = category
        self.retryable = retryable


def _chapter_source_error(response: httpx.Response) -> ChapterSourceError:
    """Decode the structured availability result without leaking raw upstream text."""
    try:
        payload = response.json()
        detail = payload.get("detail", {}) if isinstance(payload, dict) else {}
        if isinstance(detail, dict):
            return ChapterSourceError(
                str(detail.get("category") or detail.get("code") or "unknown"),
                str(detail.get("message") or "Chapter source request failed"),
                retryable=bool(detail.get("retryable", response.status_code >= 500)),
            )
    except ValueError:
        pass
    return ChapterSourceError(
        "unknown",
        _response_detail(response),
        retryable=response.status_code >= 500,
    )


class MetadataCache:
    """Small bounded read cache for metadata calls.

    Nexus runs as a single self-hosted process in the default deployment.  A
    bounded local cache prevents dashboard polling from repeatedly crossing the
    Novel/metadata service boundary while still letting writes invalidate data
    immediately.
    """

    def __init__(self, ttl: int = CACHE_TTL, max_entries: int = CACHE_MAX_ENTRIES):
        self._cache: dict[str, CacheEntry] = {}
        self._ttl = ttl
        self._max_entries = max(1, max_entries)

    def get(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry and entry.expires_at > time.time():
            return entry.data
        if entry:
            self._cache.pop(key, None)
        return None

    def set(self, key: str, data: Any, *, ttl: int | None = None):
        now = time.time()
        if key not in self._cache and len(self._cache) >= self._max_entries:
            expired = [name for name, entry in self._cache.items() if entry.expires_at <= now]
            for name in expired:
                self._cache.pop(name, None)
            if len(self._cache) >= self._max_entries:
                oldest = min(self._cache, key=lambda name: self._cache[name].expires_at)
                self._cache.pop(oldest, None)
        self._cache[key] = CacheEntry(data=data, expires_at=now + (ttl if ttl is not None else self._ttl))

    def invalidate(self, key: str):
        self._cache.pop(key, None)

    def invalidate_prefix(self, prefix: str):
        for key in list(self._cache):
            if key.startswith(prefix):
                self.invalidate(key)

    def clear(self):
        self._cache.clear()


cache = MetadataCache()
_client: httpx.AsyncClient | None = None
_client_lock = asyncio.Lock()


async def start() -> None:
    """Create the pooled metadata client during application startup."""
    global _client
    async with _client_lock:
        if _client is None or _client.is_closed:
            _client = httpx.AsyncClient(
                base_url=settings.METADATA_SERVER_URL.rstrip("/"),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )


async def close() -> None:
    """Release pooled connections during graceful application shutdown."""
    global _client
    async with _client_lock:
        if _client is not None:
            await _client.aclose()
            _client = None


async def _get_client() -> httpx.AsyncClient:
    if _client is None or _client.is_closed:
        await start()
    assert _client is not None
    return _client


_KNOWN_ERROR_CODES = frozenset({
    "source_changed", "source_timeout", "source_unavailable", "review_changed",
    "review_required", "definition_changed", "definition_missing", "run_active",
    "definition_paused", "rebind_required", "operation_id_reused", "operation_required",
    "invalid_source", "invalid_query", "budget_exhausted", "rate_limited",
    "plugin_disabled", "plugin_unavailable", "plugin_incompatible", "plugin_digest_mismatch",
    "manifest_changed", "manifest_not_ready", "manifest_capacity", "manifest_revision_required",
    "invalid_manifest_cursor", "invalid_manifest_request", "novel_not_found",
    "source_capture_changed", "source_capture_incomplete", "capture_not_found", "source_review_required",
})


def _diagnostic_path(path: str) -> str:
    # Log the route, never an absolute origin, URL credentials or query values.
    try:
        return redact_url(urlsplit(path).path or "/")[:240]
    except ValueError:
        return "<invalid-path>"


def _diagnostic_error_code(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
        detail = payload.get("detail") if isinstance(payload, dict) else None
        code = detail.get("code") if isinstance(detail, dict) else None
        return code if isinstance(code,str) and code in _KNOWN_ERROR_CODES else None
    except (ValueError, TypeError):
        return None


async def _request(
    method: str,
    path: str,
    *,
    timeout: httpx.Timeout,
    admin: bool = False,
    **kwargs: Any,
) -> httpx.Response:
    """Perform one bounded metadata request with request-id propagation."""
    client = await _get_client()
    log_path = _diagnostic_path(path)
    log_method = method.upper() if method.upper() in {"GET","HEAD","POST","PUT","PATCH","DELETE","OPTIONS"} else "UNKNOWN"
    try:
        response = await client.request(method, path, headers=_get_headers(admin=admin), timeout=timeout, **kwargs)
        response.raise_for_status()
        return response
    except httpx.TimeoutException as exc:
        logger.warning("metadata_request.timeout", method=log_method, path=log_path)
        raise RuntimeError("Metadata service did not respond before the request timeout") from exc
    except httpx.HTTPStatusError as exc:
        logger.warning("metadata_request.http_error", method=log_method, path=log_path, status_code=exc.response.status_code, error_code=_diagnostic_error_code(exc.response))
        raise RuntimeError(f"Metadata server returned HTTP {exc.response.status_code}") from exc
    except httpx.HTTPError as exc:
        logger.warning("metadata_request.failed", method=log_method, path=log_path)
        raise RuntimeError("Metadata service request failed") from exc


def _get_headers(*, admin: bool = False) -> dict:
    headers: dict[str, str] = {}
    if settings.METADATA_API_KEY:
        headers["X-API-Key"] = settings.METADATA_API_KEY
    if admin and settings.METADATA_ADMIN_API_KEY:
        headers["X-Nexus-Admin-Key"] = settings.METADATA_ADMIN_API_KEY
    request_id = get_request_id()
    if request_id:
        headers["X-Request-ID"] = request_id
    return headers


def _response_detail(response: httpx.Response) -> str:
    """Return a concise upstream explanation without leaking a traceback."""
    try:
        payload = response.json()
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if detail:
            return str(detail)
    except ValueError:
        pass
    return "Request rejected by metadata server"


async def admin_request(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
) -> Any:
    """Call Nexus Server's admin surface after Novel has authorized the user.

    The browser never receives the metadata API/admin keys; this module is the
    only bridge between the two server processes.
    """
    response = await _request(method, path, timeout=BACKGROUND_TIMEOUT, admin=True, json=json, params=params)
    return response.json() if response.content else None


async def scrape_novel_by_url(url: str, site: str) -> dict:
    cache_key = f"scrape:{url}"
    cached = cache.get(cache_key)
    if cached:
        logger.debug("Cache hit for scrape", url=url, site=site)
        return cached

    logger.info("Calling metadata server to scrape novel", url=url, site=site)

    try:
        response = await _request("POST", "/scrape/by-url", timeout=INTERACTIVE_TIMEOUT, json={"url": url, "site": site})
        data = response.json()
        cache.set(cache_key, data, ttl=30)
        logger.info("Successfully scraped novel", url=url, novel_id=data.get("novel_id"))
        return data
    except RuntimeError as exc:
        logger.error("Failed to scrape novel", url=url, error=str(exc))
        return {"success": False, "novel_id": None, "message": str(exc)}


async def wait_for_scrape_complete(
    metadata_id: int,
    timeout_seconds: int = 300,
    poll_interval_seconds: float = 2,
    job_id: str | None = None,
) -> dict:
    """Wait for the metadata worker to replace its temporary placeholder."""
    logger.info(
        "Waiting for scrape to complete",
        metadata_id=metadata_id,
        timeout_seconds=timeout_seconds,
    )
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        # Do not let the normal metadata cache keep returning the placeholder.
        cache.invalidate(f"novel:{metadata_id}")
        data = await get_novel_metadata(metadata_id)
        if data.get("status") != "scraping" and data.get("title") != "Scraping...":
            return data
        if job_id:
            response = await _request("GET", f"/api/jobs/{job_id}", timeout=INTERACTIVE_TIMEOUT)
            job = response.json()
            job_status = job.get("status")
            if job_status in {"failed", "cancelled", "archived", "paused"}:
                if job_status == "paused":
                    raise RuntimeError("Metadata import is paused. Check the source status in Operations.")
                action = "Check the failed metadata job in Operations." if job_status == "failed" else "Check the metadata job in Operations."
                raise RuntimeError(f"Metadata import {job_status}. {action}")
        await asyncio.sleep(poll_interval_seconds)

    raise TimeoutError(
        f"Metadata scrape for novel {metadata_id} did not finish within "
        f"{timeout_seconds} seconds"
    )


async def get_novel_metadata(novel_id: int) -> dict:
    cache_key = f"novel:{novel_id}"
    cached = cache.get(cache_key)
    if cached:
        logger.debug("Cache hit for novel metadata", novel_id=novel_id)
        return cached

    logger.info("Fetching novel metadata from server", novel_id=novel_id)

    response = await _request("GET", f"/novels/{novel_id}", timeout=INTERACTIVE_TIMEOUT)
    data = response.json()
    cache.set(cache_key, data)
    logger.info("Successfully fetched novel metadata", novel_id=novel_id)
    return data


async def get_hiatus_status(metadata_novel_id: int) -> dict:
    cache_key = f"hiatus:{metadata_novel_id}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    response = await _request("GET", f"/novels/{metadata_novel_id}/hiatus", timeout=INTERACTIVE_TIMEOUT)
    data = response.json()
    cache.set(cache_key, data, ttl=300)
    return data


async def get_novel_analysis(metadata_novel_id: int, *, seed_visibility: dict | None = None) -> dict:
    params = {"seed_visibility": json.dumps(seed_visibility, sort_keys=True, separators=(",", ":"))} if seed_visibility is not None else {}
    response = await _request("GET", f"/analysis/novels/{metadata_novel_id}", timeout=INTERACTIVE_TIMEOUT, params=params)
    return response.json()


async def enqueue_novel_analysis(metadata_novel_id: int, *, seed_visibility: dict | None = None) -> dict:
    """Ask the metadata service to enqueue low-priority local enrichment.

    This is deliberately a tiny authenticated proxy: the browser never gains
    direct metadata credentials and the request cannot contact a story source.
    """
    params = {"seed_visibility": json.dumps(seed_visibility, sort_keys=True, separators=(",", ":"))} if seed_visibility is not None else {}
    response = await _request("POST", f"/analysis/novels/{metadata_novel_id}/enqueue", timeout=INTERACTIVE_TIMEOUT, params=params)
    return response.json()


async def get_similar_novels(metadata_novel_id: int, limit: int = 12, *, seed_visibility: dict | None = None) -> dict:
    params={"limit":limit}
    if seed_visibility is not None:
        params['seed_visibility']=json.dumps(seed_visibility,sort_keys=True,separators=(',',':'))
    response = await _request("GET", f"/analysis/novels/{metadata_novel_id}/similar", timeout=INTERACTIVE_TIMEOUT, params=params)
    return response.json()


async def reader_story_guide(metadata_novel_id:int,*,operation:str,scope:dict,args:dict|None=None):
    """Never fall back to an unscoped guide, mutation, or artifact route."""
    import json
    from fastapi import HTTPException
    arguments=args or {}
    if len(json.dumps(arguments,ensure_ascii=False).encode())>8192:
        raise HTTPException(422,'Story Guide action exceeds the 8 KiB argument limit')
    try:
        response=await _request('POST',f'/analysis/novels/{metadata_novel_id}/story-guide/reader',
            json={'operation':operation,'scope':scope,'args':arguments},timeout=INTERACTIVE_TIMEOUT)
    except RuntimeError as exc:
        cause=exc.__cause__
        if isinstance(cause,httpx.HTTPStatusError):
            code=cause.response.status_code
            if code in (403,404,409,422):
                raise HTTPException(code,'Verified Story Guide evidence is unavailable or changed; review current chapter text before trying again') from exc
        raise HTTPException(503,'Verified Story Guide is temporarily unavailable') from exc
    if operation=='media':return response.content,response.headers.get('content-type','application/octet-stream')
    return response.json()


async def get_story_guide(metadata_novel_id: int, through_chapter: int | None = None) -> dict:
    """Fetch auxiliary story knowledge without making the detail page depend on it."""
    # Chapter zero is meaningful: it is the reader-safe empty cutoff for a
    # direct Story Guide link.  Do not collapse it to "latest" here.
    params = {"through_chapter": through_chapter} if through_chapter is not None else None
    response = await _request("GET", f"/analysis/novels/{metadata_novel_id}/story-guide", timeout=INTERACTIVE_TIMEOUT, params=params)
    return response.json()


async def get_story_guide_entities(metadata_novel_id: int, through_chapter: int) -> dict:
    response = await _request(
        "GET",
        f"/analysis/novels/{metadata_novel_id}/story-guide/entities",
        timeout=INTERACTIVE_TIMEOUT,
        params={"through_chapter": through_chapter},
    )
    return response.json()


async def get_story_guide_relationships(metadata_novel_id: int, through_chapter: int) -> dict:
    response = await _request(
        "GET",
        f"/analysis/novels/{metadata_novel_id}/story-guide/relationships",
        timeout=INTERACTIVE_TIMEOUT,
        params={"through_chapter": through_chapter},
    )
    return response.json()


async def get_story_guide_projection(metadata_novel_id: int, through_chapter: int) -> dict:
    response = await _request(
        "GET",
        f"/analysis/novels/{metadata_novel_id}/story-guide/projection",
        timeout=INTERACTIVE_TIMEOUT,
        params={"through_chapter": through_chapter},
    )
    return response.json()


async def get_story_guide_changes(metadata_novel_id: int, from_chapter: int, through_chapter: int) -> dict:
    response = await _request("GET", f"/analysis/novels/{metadata_novel_id}/story-guide/changes", timeout=INTERACTIVE_TIMEOUT, params={"from_chapter": from_chapter, "through_chapter": through_chapter})
    return response.json()


async def get_story_guide_entity_profile(metadata_novel_id: int, entity_id: str, through_chapter: int) -> dict:
    response = await _request("GET", f"/analysis/novels/{metadata_novel_id}/story-guide/entities/{entity_id}/profile", timeout=INTERACTIVE_TIMEOUT, params={"through_chapter": through_chapter})
    return response.json()


async def get_story_guide_relationship_timeline(metadata_novel_id: int, through_chapter: int, entity_id: str | None = None) -> dict:
    params = {"through_chapter": through_chapter}
    if entity_id:
        params["entity_id"] = entity_id
    response = await _request("GET", f"/analysis/novels/{metadata_novel_id}/story-guide/relationships/timeline", timeout=INTERACTIVE_TIMEOUT, params=params)
    return response.json()


async def get_story_guide_chapter_dossier(metadata_novel_id: int, chapter_number: int, through_chapter: int) -> dict:
    response = await _request(
        "GET",
        f"/analysis/novels/{metadata_novel_id}/story-guide/chapters/{chapter_number}",
        timeout=INTERACTIVE_TIMEOUT,
        params={"through_chapter": through_chapter},
    )
    return response.json()


async def get_story_guide_entity_article(metadata_novel_id: int, entity_id: str, through_chapter: int) -> dict:
    response = await _request(
        "GET",
        f"/analysis/novels/{metadata_novel_id}/story-guide/entities/{entity_id}",
        timeout=INTERACTIVE_TIMEOUT,
        params={"through_chapter": through_chapter},
    )
    return response.json()


async def regenerate_story_guide(metadata_novel_id: int, through_chapter: int | None = None) -> dict:
    # Preserve an explicit zero cutoff for spoiler-safe guide rebuilds.
    params = {"through_chapter": through_chapter} if through_chapter is not None else None
    response = await _request("POST", f"/analysis/novels/{metadata_novel_id}/story-guide/regenerate", timeout=INTERACTIVE_TIMEOUT, params=params)
    return response.json()


async def backfill_story_guide(metadata_novel_id: int) -> dict:
    """Queue analysis for chapters already stored in Nexus.

    This touches no external source and lets a library build a guide after the
    engine was enabled later.
    """
    response = await _request("POST", f"/analysis/novels/{metadata_novel_id}/story-guide/backfill", timeout=INTERACTIVE_TIMEOUT)
    return response.json()


async def create_story_guide_portrait(metadata_novel_id: int, payload: dict) -> dict:
    response = await _request("POST", f"/analysis/novels/{metadata_novel_id}/story-guide/characters/portrait", json=payload, timeout=INTERACTIVE_TIMEOUT)
    return response.json()


async def get_story_guide_media(artifact_id: str) -> tuple[bytes, str]:
    response = await _request("GET", f"/analysis/story-guide/media/{artifact_id}", timeout=INTERACTIVE_TIMEOUT)
    return response.content, response.headers.get("content-type", "image/webp")


async def get_canonical_work(metadata_novel_id: int) -> dict:
    """Return the edition group without exposing metadata-server credentials."""
    response = await _request("GET", f"/canonical-works/by-novel/{metadata_novel_id}", timeout=INTERACTIVE_TIMEOUT)
    return response.json()


def _chapter_fetch_identity(manifest_key,chapter_key,source):
    if (manifest_key is None)!=(chapter_key is None):
        raise ValueError('Supply both metadata chapter identity keys')
    if manifest_key is None:return {}
    from uuid import UUID
    for key in (manifest_key,chapter_key):
        if str(UUID(key))!=key:raise ValueError('Metadata chapter identity must be a canonical UUID')
    if not isinstance(source,dict) or set(source)!={'site','story_id','source_url'}:
        raise ChapterSourceError('chapter_review_required','Review the complete source namespace before downloading this chapter.',retryable=False)
    return {'expected_manifest_key':manifest_key,'expected_chapter_key':chapter_key,'expected_source':json.dumps(source,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)}


def _verified_chapter_fetch(value,params):
    if not isinstance(value,dict):raise RuntimeError('The metadata chapter response is malformed')
    if params and (value.get('manifest_key')!=params['expected_manifest_key'] or value.get('chapter_key')!=params['expected_chapter_key'] or value.get('source')!=json.loads(params['expected_source'])):
        raise ChapterSourceError('chapter_review_required','The metadata response does not prove the selected chapter. Upgrade the source service and review the source binding.',retryable=False)
    return value


async def fetch_public_chapter_text(metadata_novel_id: int, chapter_number: int, *, expected_manifest_key: str | None = None, expected_chapter_key: str | None = None, expected_source: dict | None = None) -> dict:
    """Delegate source access to Nexus Server; no local scraper bypass."""
    params=_chapter_fetch_identity(expected_manifest_key,expected_chapter_key,expected_source)
    path=f"/chapters/novel/{metadata_novel_id}/{chapter_number}/{'fetch-by-identity' if params else 'fetch'}"
    try:
        response = await _request("POST", path, timeout=CHAPTER_FETCH_TIMEOUT,**({'params':params} if params else {}))
    except RuntimeError as exc:
        if isinstance(exc.__cause__,httpx.HTTPStatusError):raise _chapter_source_error(exc.__cause__.response) from exc
        raise
    return _verified_chapter_fetch(response.json(),params)


def fetch_public_chapter_text_sync(metadata_novel_id: int, chapter_number: int, *, expected_manifest_key: str | None = None, expected_chapter_key: str | None = None, expected_source: dict | None = None) -> dict:
    """Worker-safe counterpart to :func:`fetch_public_chapter_text`.

    The durable download worker is synchronous and used to wrap the async
    client in a fresh ``asyncio.run`` call for every chapter.  The pooled async
    client then outlived its event loop, making later downloads fail with
    loop/connection errors.  Keep source access owned by Nexus Server, but use
    a short-lived synchronous client at this sync boundary.
    """
    params=_chapter_fetch_identity(expected_manifest_key,expected_chapter_key,expected_source)
    headers = _get_headers()
    url = f"{settings.METADATA_SERVER_URL.rstrip('/')}/chapters/novel/{metadata_novel_id}/{chapter_number}/{'fetch-by-identity' if params else 'fetch'}"
    try:
        with httpx.Client(timeout=CHAPTER_FETCH_TIMEOUT) as client:
            response = client.post(url, headers=headers,**({'params':params} if params else {}))
            if response.status_code >= 400:
                raise _chapter_source_error(response)
            response.raise_for_status()
            return _verified_chapter_fetch(response.json(),params)
    except ChapterSourceError:
        raise
    except httpx.HTTPStatusError as exc:
        detail = _response_detail(exc.response)
        raise RuntimeError(f"Metadata server returned HTTP {exc.response.status_code}: {detail}") from exc
    except httpx.TimeoutException as exc:
        raise RuntimeError("Metadata server did not respond before the chapter download timeout") from exc
    except httpx.HTTPError as exc:
        raise RuntimeError("Metadata server is unavailable for chapter downloads") from exc


async def refresh_novel_metadata(novel_id: int) -> dict:
    logger.info("Refreshing novel metadata", novel_id=novel_id)
    invalidate_novel_cache(novel_id)

    response = await _request("PUT", f"/novels/{novel_id}", timeout=BACKGROUND_TIMEOUT)
    data = response.json()
    cache.set(f"novel:{novel_id}", data)
    logger.info("Successfully refreshed novel metadata", novel_id=novel_id)
    return data


class ChapterManifestError(RuntimeError):
    """Never turn a partial or changed manifest into an authoritative chapter list."""

    def __init__(self, category: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.category = category
        self.retryable = retryable


@dataclass(frozen=True)
class ChapterManifestSnapshot:
    novel_id: int
    manifest_key: str
    revision: str
    fingerprint: str
    identity_kind: str
    total: int
    source: dict[str, Any]
    items: list[dict[str, Any]]
    protocol: int = 1
    complete: bool = True
    source_complete: bool = False
    deletion_authoritative: bool = False
    source_capture_id: str | None = None
    source_authority_kind: str | None = None
    source_review_id: str | None = None
    source_lineage: list[dict[str, Any]] = field(default_factory=list)
    source_lineage_fingerprint: str | None = None


MAX_MANIFEST_ITEMS = 1_000_000
MAX_MANIFEST_BYTES = 128 * 1024 * 1024


def _manifest_invalid(message: str):
    raise ChapterManifestError('manifest_invalid', message)


def _manifest_uuid(value):
    from uuid import UUID
    if not isinstance(value, str) or len(value) not in {32, 36}:
        _manifest_invalid('The metadata manifest has an invalid chapter identity')
    try:
        return str(UUID(value))
    except ValueError as exc:
        raise ChapterManifestError('manifest_invalid', 'The metadata manifest has an invalid chapter identity') from exc


def _manifest_integer(value, minimum, maximum):
    return type(value) is int and minimum <= value <= maximum


def _manifest_item(value, novel_id):
    expected = {'id', 'chapter_key', 'site', 'story_id', 'chapter_id', 'chapter_number', 'title', 'url', 'category', 'word_count', 'identity_kind'}
    if not isinstance(value, dict) or set(value) != expected:
        _manifest_invalid('The metadata manifest contains an invalid chapter record')
    if not _manifest_integer(value.get('id'), 1, 2147483647) or not _manifest_integer(value.get('chapter_number'), -2147483648, 2147483647):
        _manifest_invalid('The metadata manifest contains an invalid chapter number or record identity')
    _manifest_uuid(value.get('chapter_key'))
    if not isinstance(value.get('identity_kind'), str) or value['identity_kind'] not in {'stable_source_id', 'positional', 'unknown'}:
        _manifest_invalid('The metadata manifest contains an invalid chapter identity policy')
    for key in ('story_id', 'chapter_id'):
        if not _manifest_integer(value.get(key), -9223372036854775808, 9223372036854775807):
            _manifest_invalid('The metadata manifest contains an invalid source chapter identity')
    if not isinstance(value.get('site'), str) or not 1 <= len(value['site']) <= 64:
        _manifest_invalid('The metadata manifest contains an invalid source')
    for key, maximum in [('title', 10000), ('url', 10000)]:
        if key not in value or (value[key] is not None and (not isinstance(value[key], str) or len(value[key]) > maximum)):
            _manifest_invalid('The metadata manifest contains an invalid chapter label or URL')
    if not isinstance(value.get('category'), str) or not 1 <= len(value['category']) <= 32:
        _manifest_invalid('The metadata manifest contains an invalid chapter category')
    if 'word_count' not in value or (value['word_count'] is not None and not _manifest_integer(value['word_count'], 0, 9223372036854775807)):
        _manifest_invalid('The metadata manifest contains an invalid word count')
    if 'novel_fk' in value and value['novel_fk'] != novel_id:
        _manifest_invalid('The metadata manifest contains chapters from another story')


async def _manifest_request(path, **params):
    try:
        response = await _request('GET', path, timeout=INTERACTIVE_TIMEOUT, params=params)
        return response.json()
    except ChapterManifestError:
        raise
    except (ValueError, TypeError) as exc:
        raise ChapterManifestError('manifest_invalid', 'Metadata returned an unreadable chapter manifest') from exc
    except (RuntimeError, httpx.HTTPError) as exc:
        cause = exc if isinstance(exc, httpx.HTTPStatusError) else exc.__cause__
        if isinstance(cause, httpx.HTTPStatusError):
            status = cause.response.status_code
            try:
                payload = cause.response.json()
                detail = payload.get('detail', {}) if isinstance(payload, dict) else {}
                code = detail.get('code') if isinstance(detail, dict) else None
            except ValueError:
                code = None
            if code == 'manifest_capacity':
                raise ChapterManifestError('manifest_limit', 'The complete chapter manifest exceeds the metadata service capacity. No partial list was saved.') from exc
            if code == 'manifest_not_ready':
                raise ChapterManifestError('upgrade_required', 'Complete the metadata chapter identity migration before synchronizing chapters.') from exc
            if status == 422:
                raise ChapterManifestError('manifest_invalid', 'The metadata service rejected this chapter manifest request. No partial list was saved.') from exc
            if status == 404 and code == 'novel_not_found':
                raise ChapterManifestError('story_not_found', 'This metadata story no longer exists') from exc
            if status == 404 and code == 'capture_not_found':
                raise ChapterManifestError('manifest_changed', 'The saved source observation is no longer available. Refresh the chapter list.', retryable=True) from exc
            if status == 409:
                raise ChapterManifestError('manifest_changed', 'The chapter list changed while it was being read. Retry the complete manifest.', retryable=True) from exc
            if status in {404, 405, 501}:
                raise ChapterManifestError('upgrade_required', 'This metadata service does not provide the required complete chapter manifest. Upgrade it before synchronizing chapters.') from exc
        raise ChapterManifestError('manifest_unavailable', 'The metadata chapter manifest is temporarily unavailable. No partial list was saved.', retryable=True) from exc


def _manifest_cache_prefix(novel_id):
    return f'chapter-manifest:v1:{settings.METADATA_SERVER_URL.rstrip("/")}:{novel_id}:'


async def get_chapter_manifest(novel_id: int, page_size: int = 1000, *, force_refresh: bool = False) -> ChapterManifestSnapshot:
    """Prefer a verified source capture, otherwise read one database revision.

    Database completeness alone never establishes current source membership.
    Raw source observations require review; they cannot silently fall back to
    stale database rows. Callers still review private topology changes explicitly.
    """
    import copy
    import hashlib
    import re
    if not _manifest_integer(novel_id, 1, 2147483647) or not _manifest_integer(page_size, 1, 1000):
        raise ValueError('A positive story identity and page size between 1 and 1000 are required')
    if type(force_refresh) is not bool:
        raise ValueError('force_refresh must be a boolean')
    if force_refresh:
        cache.invalidate_prefix(_manifest_cache_prefix(novel_id))
    cache_root = _manifest_cache_prefix(novel_id) + str(page_size) + ':'
    capability = await _manifest_request('/chapters/manifest-capabilities')
    if (not isinstance(capability, dict) or not isinstance(capability.get('protocols'), list)
            or not any(type(protocol) is int and protocol == 1 for protocol in capability['protocols'])
            or capability.get('ordering') != 'chapter_number,id'):
        raise ChapterManifestError('upgrade_required', 'The metadata service does not declare complete revision-bound chapter manifests. Upgrade it before synchronizing chapters.')
    maximum = capability.get('max_page_size')
    if not _manifest_integer(maximum, 1, 1000):
        _manifest_invalid('The metadata manifest capability has an invalid page bound')
    page_size = min(page_size, maximum)
    source_protocols = capability.get('source_manifest_protocols', [])
    if not isinstance(source_protocols, list) or any(type(value) is not int for value in source_protocols):
        _manifest_invalid('Metadata returned invalid source manifest capabilities')
    if 1 in source_protocols:
        from app.services.source_capture_client import read_source_capture
        captured = await read_source_capture(novel_id, page_size=page_size)
        if captured is not None:
            return captured
    cursor = None
    invariant = None
    items, seen_ids, seen_keys, seen_numbers, seen_cursors = [], set(), set(), set(), set()
    total_bytes = 0
    hasher = hashlib.sha256()
    while True:
        params = {'limit': page_size}
        if cursor is not None:
            params.update(cursor=cursor, revision=invariant['revision'])
        page = await _manifest_request(f'/chapters/novel/{novel_id}/manifest', **params)
        if not isinstance(page, dict):
            _manifest_invalid('Metadata returned an invalid chapter manifest page')
        keys = ('protocol', 'novel_id', 'manifest_key', 'revision', 'fingerprint', 'total', 'source', 'identity_kind', 'complete', 'source_complete', 'deletion_authoritative')
        required = {key: page.get(key) for key in keys}
        if page.get('protocol') != 1 or type(page.get('protocol')) is not int or type(page.get('novel_id')) is not int or page.get('novel_id') != novel_id:
            _manifest_invalid('Metadata returned a different story or manifest protocol')
        _manifest_uuid(page.get('manifest_key'))
        if any(not isinstance(page.get(key), str) or not re.fullmatch('[0-9a-f]{64}', page[key]) for key in ('revision', 'fingerprint')):
            _manifest_invalid('Metadata returned an invalid manifest revision or fingerprint')
        if not _manifest_integer(page.get('total'), 0, MAX_MANIFEST_ITEMS):
            raise ChapterManifestError('manifest_limit', 'The complete chapter manifest exceeds the supported record bound')
        if page.get('identity_kind') not in {'stable_source_id', 'positional', 'unknown'}:
            _manifest_invalid('Metadata returned an unknown source chapter identity policy')
        if page.get('complete') is not True or any(type(page.get(key)) is not bool for key in ('source_complete', 'deletion_authoritative', 'has_more')):
            _manifest_invalid('Metadata did not certify a complete database manifest')
        if page['source_complete'] or page['deletion_authoritative']:
            _manifest_invalid('This client does not support destructive source manifest authority')
        source = page.get('source')
        if (not isinstance(source, dict) or set(source) != {'site', 'story_id', 'source_url'}
                or (source['site'] is not None and (not isinstance(source['site'], str) or not 1 <= len(source['site']) <= 64))
                or (source['story_id'] is not None and not _manifest_integer(source['story_id'], -9223372036854775808, 9223372036854775807))
                or (source['source_url'] is not None and (not isinstance(source['source_url'], str) or len(source['source_url']) > 10000))):
            _manifest_invalid('Metadata returned an invalid source identity')
        if invariant is None:
            invariant = required
            cache_key = cache_root + page['manifest_key'] + ':' + page['revision'] + ':' + page['fingerprint']
            header = {key: page[key] for key in ('protocol', 'novel_id', 'manifest_key', 'source', 'identity_kind', 'total')}
            hasher.update(json.dumps(header, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode() + b'\n')
        elif required != invariant:
            raise ChapterManifestError('manifest_changed', 'The chapter manifest changed between pages. Retry the whole snapshot.', retryable=True)
        rows = page.get('items')
        if not isinstance(rows, list) or len(rows) > page_size or len(items) + len(rows) > invariant['total']:
            _manifest_invalid('Metadata returned an inconsistent chapter manifest count')
        for item in rows:
            _manifest_item(item, novel_id)
            key = _manifest_uuid(item['chapter_key'])
            if item['id'] in seen_ids or key in seen_keys or item['chapter_number'] in seen_numbers:
                _manifest_invalid('Metadata returned duplicate chapter identities or numbers')
            if items and (item['chapter_number'], item['id']) <= (items[-1]['chapter_number'], items[-1]['id']):
                _manifest_invalid('Metadata returned chapters outside manifest order')
            encoded = json.dumps(item, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
            total_bytes += len(encoded)
            if total_bytes > MAX_MANIFEST_BYTES:
                raise ChapterManifestError('manifest_limit', 'The complete chapter manifest exceeds its metadata byte budget')
            # Protocol v1 hashes the declared source/header and every ordered record.
            hasher.update(encoded + b'\n')
            items.append(item)
            seen_ids.add(item['id']); seen_keys.add(key); seen_numbers.add(item['chapter_number'])
        next_cursor = page.get('next_cursor')
        if not page['has_more']:
            if next_cursor is not None or len(items) != invariant['total']:
                _manifest_invalid('Metadata ended the chapter manifest before its declared total')
        elif not rows or not isinstance(next_cursor, str) or not 1 <= len(next_cursor) <= 8192 or next_cursor in seen_cursors or len(items) >= invariant['total']:
            _manifest_invalid('Metadata returned an invalid or repeated chapter manifest cursor')
        # Observe the current identity/revision before using a complete cache.
        # A work deleted/recreated at the same numeric ID cannot inherit an old
        # snapshot, and mutable cached dictionaries never escape to callers.
        if cursor is None:
            cached = cache.get(cache_key)
            if isinstance(cached, ChapterManifestSnapshot):
                if any(getattr(cached, key) != value for key, value in invariant.items()) or cached.items[:len(items)] != items:
                    _manifest_invalid('Metadata changed a cached manifest without changing its revision and fingerprint')
                return copy.deepcopy(cached)
        if not page['has_more']:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    if hasher.hexdigest() != invariant['fingerprint']:
        _manifest_invalid('The complete chapter manifest does not match its fingerprint')
    result = ChapterManifestSnapshot(items=items, **{key: invariant[key] for key in keys if key != 'items'})
    cache.set(cache_key, copy.deepcopy(result))
    return result


async def get_chapters_from_metadata(novel_id: int, limit: int = 1000, *, force_refresh: bool = False) -> list[dict[str, Any]]:
    """Compatibility list view; limit controls page size, never total story size."""
    return (await get_chapter_manifest(novel_id, page_size=limit, force_refresh=force_refresh)).items

async def get_author_metadata(author_id: int, include_novels: bool = False) -> dict:
    cache_key = f"author:{author_id}:{include_novels}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    response = await _request("GET", f"/authors/{author_id}", timeout=INTERACTIVE_TIMEOUT, params={"include_novels": include_novels})
    data = response.json()
    cache.set(cache_key, data)
    return data


async def put_follow_target(kind: str, site: str, key: str, name: str | None, follower_count: int) -> dict:
    """Tell the metadata server how many readers follow an author page or series."""
    response = await _request(
        "PUT", "/follow-targets", timeout=INTERACTIVE_TIMEOUT,
        json={"kind": kind, "site": site, "key": key, "name": name, "follower_count": follower_count},
    )
    return response.json()


async def get_follow_target(target_id: int) -> dict:
    response = await _request("GET", f"/follow-targets/{target_id}", timeout=INTERACTIVE_TIMEOUT)
    return response.json()


async def get_author_works(author_id: int) -> dict:
    """An author with their catalog works and same-name profiles on other sites."""
    cache_key = f"author-works:{author_id}"
    cached = cache.get(cache_key)
    if cached:
        return cached
    response = await _request("GET", f"/follow-targets/authors/{author_id}", timeout=INTERACTIVE_TIMEOUT)
    data = response.json()
    cache.set(cache_key, data, ttl=60)
    return data


def _clean_list(values: Optional[list[str]]) -> Optional[list[str]]:
    cleaned = [value.strip() for value in values or [] if value and value.strip()]
    return cleaned or None


async def list_novels_metadata(
    site: Optional[str] = None,
    author: Optional[str] = None,
    title: Optional[str] = None,
    q: Optional[str] = None,
    tag: Optional[list[str]] = None,
    tag_mode: str = "all",
    fandom: Optional[list[str]] = None,
    genre: Optional[list[str]] = None,
    exclude_tag: Optional[list[str]] = None,
    exclude_fandom: Optional[list[str]] = None,
    exclude_genre: Optional[list[str]] = None,
    exclude_author: Optional[list[str]] = None,
    exclude_text: Optional[list[str]] = None,
    language: Optional[list[str]] = None,
    complete_only: bool = False,
    hide_inactive: bool = False,
    crossover: Optional[bool] = None,
    status: Optional[str] = None,
    min_word_count: Optional[int] = None,
    min_favorites: Optional[int] = None,
    min_follows: Optional[int] = None,
    min_reviews: Optional[int] = None,
    min_chapter_count: Optional[int] = None,
    max_word_count: Optional[int] = None,
    updated_since_days: Optional[int] = None,
    label: Optional[str] = None,
    label_origin: Optional[str] = None,
    import_state: Optional[str] = None,
    similar_to: Optional[int] = None,
    content_rating: Optional[list[str]] = None,
    sort_by: str = "updated",
    sort_order: str = "desc",
    limit: int = 100,
    cursor: Optional[int] = None,
    canonical_include: Optional[list[str]] = None,
    canonical_exclude: Optional[list[str]] = None,
    grouped: bool = False,
    seed_visibility: dict | None = None,
) -> dict:
    params: dict[str, Any] = {"limit": limit}
    if site:
        params["site"] = site
    if author:
        params["author"] = author
    if title:
        params["title"] = title
    if q:
        params["q"] = q
    # Repeatable parameters stay lists so httpx sends ?tag=a&tag=b.
    for name, value in {
        "tag": _clean_list(tag),
        "tag_mode": tag_mode if tag_mode != "all" else None,
        "fandom": _clean_list(fandom),
        "genre": _clean_list(genre),
        "exclude_tag": _clean_list(exclude_tag),
        "exclude_fandom": _clean_list(exclude_fandom),
        "exclude_genre": _clean_list(exclude_genre),
        "exclude_author": _clean_list(exclude_author),
        "exclude_text": _clean_list(exclude_text),
        "language": _clean_list(language),
        "complete_only": True if complete_only else None,
        "hide_inactive": True if hide_inactive else None,
        "crossover": crossover,
        "status": status,
        "min_word_count": min_word_count,
        "min_favorites": min_favorites,
        "min_follows": min_follows,
        "min_reviews": min_reviews,
        "min_chapter_count": min_chapter_count,
        "max_word_count": max_word_count,
        "updated_since_days": updated_since_days,
        "label": label,
        "label_origin": label_origin,
        "import_state": import_state,
        "similar_to": similar_to,
        "content_rating": _clean_list(content_rating),
        "canonical_include": _clean_list(canonical_include),
        "canonical_exclude": _clean_list(canonical_exclude),
        "seed_visibility": json.dumps(seed_visibility,sort_keys=True,separators=(',',':')) if seed_visibility is not None else None,
        "sort_by": sort_by,
        "sort_order": sort_order,
    }.items():
        if value is not None and value != "":
            params[name] = value
    if cursor:
        params["cursor"] = cursor

    cache_key = ("works:list:" if grouped else "novels:list:") + repr(sorted(params.items()))
    cached = cache.get(cache_key)
    if cached:
        return cached

    response = await _request("GET", "/catalog/works" if grouped else "/novels/", timeout=INTERACTIVE_TIMEOUT, params=params)
    data = response.json()
    cache.set(cache_key, data, ttl=30)
    return data


async def list_fandoms_metadata(
    *,
    site: Optional[str] = None,
    media_type: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return the source-aware fandom taxonomy for searchable UI controls."""
    params: dict[str, Any] = {"limit": limit}
    if site:
        params["site"] = site
    if media_type:
        params["media_type"] = media_type
    if query:
        params["q"] = query
    cache_key = f"fandoms:{tuple(sorted(params.items()))}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    response = await _request("GET", "/fandoms", timeout=INTERACTIVE_TIMEOUT, params=params)
    data: list[dict[str, Any]] = response.json()
    cache.set(cache_key, data, ttl=600)
    return data


def invalidate_novel_cache(novel_id: int):
    logger.debug("Invalidating novel cache", novel_id=novel_id)
    cache.invalidate(f"novel:{novel_id}")
    cache.invalidate(f"chapters:{novel_id}")
    cache.invalidate_prefix(_manifest_cache_prefix(novel_id))


def clear_cache():
    logger.info("Clearing all metadata cache")
    cache.clear()


async def search_novel_by_url(url: str) -> dict:
    title_from_url = url.split("/")[-1] if url else ""
    title = title_from_url.replace("-", " ").replace("_", " ").title()

    cache_key = f"novels:search:{url}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    response = await _request("GET", "/novels/", timeout=INTERACTIVE_TIMEOUT, params={"title": title, "limit": 5})
    data = response.json()
    cache.set(cache_key, data, ttl=30)
    return data


async def live_capabilities() -> dict:
    """Current installed source capabilities; never start source requests."""
    try:
        response = await _request('GET', '/search/capabilities', timeout=INTERACTIVE_TIMEOUT)
        return response.json()
    except (RuntimeError, ValueError, TypeError) as exc:
        from fastapi import HTTPException
        raise HTTPException(503, detail='Source capabilities are temporarily unavailable') from exc


async def live_listing(kind: str, params: dict) -> dict:
    """One page of a live site listing: ``kind`` is live, browse or user-list.

    The metadata server reports source failures per site in ``error``; a
    failure to reach the metadata server itself is reported the same way so
    one slow site never breaks a multi-site search.
    """
    try:
        response = await _request("GET", f"/search/{kind}", timeout=LIVE_LISTING_TIMEOUT, params=params)
        return response.json()
    except (RuntimeError, ValueError, TypeError) as exc:
        code = "timeout" if "timeout" in str(exc).lower() else "metadata_unavailable"
        return {"site": params.get("site"), "page": params.get("page", 1), "results": [],
                "error": {"code": code, "message": "The source service is temporarily unavailable"}}


async def source_health() -> list[dict]:
    """Per-site health rows from the metadata server (API-key read, cached briefly)."""
    cache_key = "source-health"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    response = await _request("GET", "/api/jobs/source-health", timeout=INTERACTIVE_TIMEOUT)
    data = response.json()
    cache.set(cache_key, data, ttl=30)
    return data
