import asyncio
import httpx
import time
from typing import Optional, Any
from dataclasses import dataclass

from config.settings import settings
from app.logging_config import get_logger, get_request_id

logger = get_logger("metadata_client")

CACHE_TTL = 300


@dataclass
class CacheEntry:
    data: Any
    expires_at: float


class MetadataCache:
    def __init__(self, ttl: int = CACHE_TTL):
        self._cache: dict[str, CacheEntry] = {}
        self._ttl = ttl

    def get(self, key: str) -> Optional[Any]:
        entry = self._cache.get(key)
        if entry and entry.expires_at > time.time():
            return entry.data
        return None

    def set(self, key: str, data: Any):
        self._cache[key] = CacheEntry(data=data, expires_at=time.time() + self._ttl)

    def invalidate(self, key: str):
        self._cache.pop(key, None)

    def clear(self):
        self._cache.clear()


cache = MetadataCache()


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

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{settings.METADATA_SERVER_URL}/scrape/by-url",
                json={"url": url, "site": site},
                headers=_get_headers(),
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            cache.set(cache_key, data)
            logger.info(
                "Successfully scraped novel", url=url, novel_id=data.get("novel_id")
            )
            return data
        except httpx.HTTPError as e:
            logger.error("Failed to scrape novel", url=url, error=str(e))
            return {"success": False, "novel_id": None, "message": str(e)}


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

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{settings.METADATA_SERVER_URL}/novels/{novel_id}",
            headers=_get_headers(),
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        cache.set(cache_key, data)
        logger.info("Successfully fetched novel metadata", novel_id=novel_id)
        return data


async def refresh_novel_metadata(novel_id: int) -> dict:
    logger.info("Refreshing novel metadata", novel_id=novel_id)
    cache.invalidate(f"novel:{novel_id}")

    async with httpx.AsyncClient() as client:
        response = await client.put(
            f"{settings.METADATA_SERVER_URL}/novels/{novel_id}",
            headers=_get_headers(),
            timeout=120.0,
        )
        response.raise_for_status()
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

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{settings.METADATA_SERVER_URL}/chapters/novel/{novel_id}",
            params={"limit": limit},
            headers=_get_headers(),
            timeout=30.0,
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        chapters: list[dict[str, Any]] = data.get("data", [])
        cache.set(cache_key, chapters)
        logger.info(
            "Successfully fetched chapters", novel_id=novel_id, count=len(chapters)
        )
        return chapters


async def get_author_metadata(author_id: int, include_novels: bool = False) -> dict:
    cache_key = f"author:{author_id}:{include_novels}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{settings.METADATA_SERVER_URL}/authors/{author_id}",
            params={"include_novels": include_novels},
            headers=_get_headers(),
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        cache.set(cache_key, data)
        return data


async def list_novels_metadata(
    site: Optional[str] = None,
    author: Optional[str] = None,
    title: Optional[str] = None,
    tag: Optional[str] = None,
    genre: Optional[str] = None,
    status: Optional[str] = None,
    min_word_count: Optional[int] = None,
    min_favorites: Optional[int] = None,
    min_follows: Optional[int] = None,
    min_reviews: Optional[int] = None,
    min_chapter_count: Optional[int] = None,
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
        "genre": genre,
        "status": status,
        "min_word_count": min_word_count,
        "min_favorites": min_favorites,
        "min_follows": min_follows,
        "min_reviews": min_reviews,
        "min_chapter_count": min_chapter_count,
    }.items():
        if value is not None and value != "":
            params[name] = value
    if cursor:
        params["cursor"] = cursor

    cache_key = f"novels:list:{hash(frozenset(params.items()))}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{settings.METADATA_SERVER_URL}/novels/",
            params=params,
            headers=_get_headers(),
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        cache.set(cache_key, data)
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

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{settings.METADATA_SERVER_URL}/novels/",
            params={"title": title, "limit": 5},
            headers=_get_headers(),
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        cache.set(cache_key, data)
        return data
