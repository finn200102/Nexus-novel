import asyncio
import httpx
import time
from typing import Optional, Any
from dataclasses import dataclass

from config.settings import settings
from app.logging_config import get_logger, get_request_id

logger = get_logger("metadata_client")

CACHE_TTL = 300
CACHE_MAX_ENTRIES = 512
INTERACTIVE_TIMEOUT = httpx.Timeout(15.0, connect=3.0)
BACKGROUND_TIMEOUT = httpx.Timeout(20.0, connect=3.0)


@dataclass
class CacheEntry:
    data: Any
    expires_at: float


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


async def _request(method: str, path: str, *, timeout: httpx.Timeout, **kwargs: Any) -> httpx.Response:
    """Perform one bounded metadata request with request-id propagation."""
    client = await _get_client()
    try:
        response = await client.request(method, path, headers=_get_headers(), timeout=timeout, **kwargs)
        response.raise_for_status()
        return response
    except httpx.TimeoutException as exc:
        logger.warning("metadata_request.timeout", method=method, path=path)
        raise RuntimeError("Metadata service did not respond before the request timeout") from exc
    except httpx.HTTPError as exc:
        logger.warning("metadata_request.failed", method=method, path=path, error=str(exc))
        raise RuntimeError("Metadata service request failed") from exc


def _get_headers() -> dict:
    request_id = get_request_id()
    if request_id:
        return {"X-Request-ID": request_id}
    return {}


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


async def refresh_novel_metadata(novel_id: int) -> dict:
    logger.info("Refreshing novel metadata", novel_id=novel_id)
    cache.invalidate(f"novel:{novel_id}")

    response = await _request("PUT", f"/novels/{novel_id}", timeout=BACKGROUND_TIMEOUT)
    data = response.json()
    cache.set(f"novel:{novel_id}", data)
    logger.info("Successfully refreshed novel metadata", novel_id=novel_id)
    return data


async def get_chapters_from_metadata(
    novel_id: int, limit: int = 1000
) -> list[dict[str, Any]]:
    cache_key = f"chapters:{novel_id}"
    cached = cache.get(cache_key)
    if cached:
        logger.debug("Cache hit for chapters", novel_id=novel_id, count=len(cached))
        return cached

    logger.info(
        "Fetching chapters from metadata server", novel_id=novel_id, limit=limit
    )

    response = await _request("GET", f"/chapters/novel/{novel_id}", timeout=INTERACTIVE_TIMEOUT, params={"limit": limit})
    data: dict[str, Any] = response.json()
    chapters: list[dict[str, Any]] = data.get("data", [])
    cache.set(cache_key, chapters)
    logger.info("Successfully fetched chapters", novel_id=novel_id, count=len(chapters))
    return chapters


async def get_author_metadata(author_id: int, include_novels: bool = False) -> dict:
    cache_key = f"author:{author_id}:{include_novels}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    response = await _request("GET", f"/authors/{author_id}", timeout=INTERACTIVE_TIMEOUT, params={"include_novels": include_novels})
    data = response.json()
    cache.set(cache_key, data)
    return data


async def list_novels_metadata(
    site: Optional[str] = None,
    author: Optional[str] = None,
    title: Optional[str] = None,
    tag: Optional[str] = None,
    fandom: Optional[str] = None,
    genre: Optional[str] = None,
    status: Optional[str] = None,
    min_word_count: Optional[int] = None,
    min_favorites: Optional[int] = None,
    min_follows: Optional[int] = None,
    min_reviews: Optional[int] = None,
    min_chapter_count: Optional[int] = None,
    sort_by: str = "updated",
    sort_order: str = "desc",
    limit: int = 100,
    cursor: Optional[int] = None,
) -> dict:
    params: dict[str, Any] = {"limit": limit}
    if site:
        params["site"] = site
    if author:
        params["author"] = author
    if title:
        params["title"] = title
    for name, value in {
        "tag": tag,
        "fandom": fandom,
        "genre": genre,
        "status": status,
        "min_word_count": min_word_count,
        "min_favorites": min_favorites,
        "min_follows": min_follows,
        "min_reviews": min_reviews,
        "min_chapter_count": min_chapter_count,
        "sort_by": sort_by,
        "sort_order": sort_order,
    }.items():
        if value is not None and value != "":
            params[name] = value
    if cursor:
        params["cursor"] = cursor

    cache_key = f"novels:list:{hash(frozenset(params.items()))}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    response = await _request("GET", "/novels/", timeout=INTERACTIVE_TIMEOUT, params=params)
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
