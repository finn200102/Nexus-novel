import httpx
import time
from typing import Optional, Any
from dataclasses import dataclass

from config.settings import settings
from app.logging_config import get_logger

logger = get_logger(__name__)

CACHE_TTL = 300


@dataclass
class CacheEntry:
    data: dict
    expires_at: float


class MetadataCache:
    def __init__(self, ttl: int = CACHE_TTL):
        self._cache: dict[str, CacheEntry] = {}
        self._ttl = ttl

    def get(self, key: str) -> Optional[dict]:
        entry = self._cache.get(key)
        if entry and entry.expires_at > time.time():
            return entry.data
        return None

    def set(self, key: str, data: dict):
        self._cache[key] = CacheEntry(data=data, expires_at=time.time() + self._ttl)

    def invalidate(self, key: str):
        self._cache.pop(key, None)

    def clear(self):
        self._cache.clear()


cache = MetadataCache()


async def scrape_novel_by_url(url: str, site: str) -> dict:
    """
    Call the metadata server to start scraping a novel.
    Returns: { success: bool, novel_id: int | None, message: str }
    If success is False or novel_id is None, the scrape failed.
    """
    cache_key = f"scrape:{url}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{settings.METADATA_SERVER_URL}/scrape/by-url",
                json={"url": url, "site": site},
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            cache.set(cache_key, data)
            return data
        except httpx.HTTPError as e:
            logger.error(f"Failed to scrape novel: {e}")
            return {"success": False, "novel_id": None, "message": str(e)}


async def wait_for_scrape_complete(
    metadata_id: int, wait_seconds: int = 3
) -> dict | None:
    """
    Wait for scrape to complete and return metadata.
    Returns novel metadata dict if successful, None if failed.
    """
    time.sleep(wait_seconds)
    try:
        return await get_novel_metadata(metadata_id)
    except Exception as e:
        logger.warning(f"Failed to get metadata after waiting: {e}")
        return None


async def get_novel_metadata(novel_id: int) -> dict:
    cache_key = f"novel:{novel_id}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{settings.METADATA_SERVER_URL}/novels/{novel_id}",
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        cache.set(cache_key, data)
        return data


async def refresh_novel_metadata(novel_id: int) -> dict:
    cache.invalidate(f"novel:{novel_id}")

    async with httpx.AsyncClient() as client:
        response = await client.put(
            f"{settings.METADATA_SERVER_URL}/novels/{novel_id}",
            timeout=120.0,
        )
        response.raise_for_status()
        data = response.json()
        cache.set(f"novel:{novel_id}", data)
        return data


async def get_chapters_from_metadata(
    novel_id: int, limit: int = 1000
) -> list[dict[str, Any]]:
    cache_key = f"chapters:{novel_id}"
    cached = cache.get(cache_key)
    if cached:
        return cached

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{settings.METADATA_SERVER_URL}/chapters/novel/{novel_id}",
            params={"limit": limit},
            timeout=30.0,
        )
        response.raise_for_status()
        data: dict[str, Any] = response.json()
        chapters: list[dict[str, Any]] = data.get("data", [])
        cache.set(cache_key, chapters)
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
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        cache.set(cache_key, data)
        return data


def invalidate_novel_cache(novel_id: int):
    cache.invalidate(f"novel:{novel_id}")
    cache.invalidate(f"chapters:{novel_id}")


def clear_cache():
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
            timeout=30.0,
        )
        response.raise_for_status()
        data = response.json()
        cache.set(cache_key, data)
        return data
