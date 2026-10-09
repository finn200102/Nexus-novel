"""Author support links, re-validated before they leave the API.

Only https links on the known platforms pass. The kind is derived from the
host, so a stored or upstream "kind" value is never trusted.
"""

from typing import Any
from urllib.parse import urlsplit

# Host suffix -> kind. Matches nexus-server (schemas/support_links.py).
SUPPORT_PLATFORMS: tuple[tuple[str, str], ...] = (
    ("patreon.com", "patreon"),
    ("ko-fi.com", "kofi"),
    ("subscribestar.com", "subscribestar"),
    ("subscribestar.adult", "subscribestar"),
    ("buymeacoffee.com", "buymeacoffee"),
    ("liberapay.com", "liberapay"),
)
MAX_LINKS = 10
MAX_URL_LENGTH = 500


def _kind_for(url: str) -> str | None:
    if not url or len(url) > MAX_URL_LENGTH:
        return None
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
        return None
    host = parts.hostname.lower()
    host = host[4:] if host.startswith("www.") else host
    for domain, kind in SUPPORT_PLATFORMS:
        if host == domain or host.endswith("." + domain):
            return kind
    return None


def clean_support_links(raw: Any) -> list[dict[str, str]]:
    """Return the valid {kind, url} links, de-duplicated, at most MAX_LINKS."""
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    cleaned: list[dict[str, str]] = []
    for item in raw:
        url = str(item.get("url") or "").strip() if isinstance(item, dict) else ""
        kind = _kind_for(url)
        if kind is None or url in seen:
            continue
        seen.add(url)
        cleaned.append({"kind": kind, "url": url})
        if len(cleaned) >= MAX_LINKS:
            break
    return cleaned
