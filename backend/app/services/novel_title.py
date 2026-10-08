"""Human-readable story titles from metadata, import jobs and URLs.

Mirrors nexus-novel/frontend/src/utils/displayTitle.ts and
nexus-server/src/nexus/scraper/titles.py. Keep the three implementations in sync.
"""

import re
from urllib.parse import unquote, urlsplit

_PLACEHOLDER_TITLES = {"scraping...", "unknown", "untitled"}
_SMALL_WORDS = {
    "a", "an", "and", "as", "at", "by", "for", "from", "in", "of", "on", "or", "the", "to", "with",
}
_THREADMARKS_PREFIX = re.compile(r"^threadmarks\s+for\s*:\s*", re.IGNORECASE)
_PERCENT_ESCAPE = re.compile(r"%[0-9A-Fa-f]{2}")


def _safe_decode(value: str) -> str:
    try:
        return unquote(value, errors="strict")
    except UnicodeDecodeError:
        return _PERCENT_ESCAPE.sub(" ", value)


def _title_case(words: str) -> str:
    out = []
    for index, word in enumerate(w for w in words.split(" ") if w):
        lower = word.lower()
        if index > 0 and lower in _SMALL_WORDS:
            out.append(lower)
        else:
            out.append(lower[:1].upper() + lower[1:])
    return " ".join(out)


def _from_slug(slug: str) -> str:
    return _title_case(re.sub(r"[-_]+", " ", slug).strip())


def title_from_url(url: str | None) -> str:
    """Readable fallback from the last URL path segment ("" if none usable)."""
    if not url:
        return ""
    segments = [s for s in _safe_decode(urlsplit(url).path).split("/") if s]
    if not segments or segments[-1].isdigit():
        return ""
    return _from_slug(segments[-1])


def clean_title(raw: str | None, url: str | None = None) -> str:
    """Return a display-ready title. Falls back to the URL slug when raw is unusable.

    Returns "" only when neither the raw title nor the URL yields anything.
    """
    title = _safe_decode((raw or "").strip())
    title = _THREADMARKS_PREFIX.sub("", title).strip()
    if title.lower() in _PLACEHOLDER_TITLES:
        title = ""
    if not title:
        return title_from_url(url)
    # Slugs are lowercase with dashes or underscores; mixed-case titles are left alone.
    if title == title.lower() and re.search(r"[-_]", title):
        return _from_slug(title)
    return re.sub(r"\s+", " ", title)
