"""Per-user global blocklist: hide tags, fandoms, genres, authors or words.

Discovery requests merge these rules into the metadata server's exclude
parameters, so the server filters first. Results are checked again here so
that a rule also applies to fields the server matches more loosely.

An administrator's content limits for the user (see content_limit_service)
ride along: blocked tags join the tag rules, and the rating limit becomes a
``content_rating`` filter and a final row check.
"""

from sqlalchemy.orm import Session

from app.models.blocklist import BLOCKLIST_KINDS, BlocklistEntry
from app.models.user import User
from app.services import content_limit_service

# Blocklist kind -> the exclude_* parameter it feeds on discovery requests.
EXCLUDE_PARAM_BY_KIND = {
    "tag": "exclude_tag",
    "fandom": "exclude_fandom",
    "genre": "exclude_genre",
    "author": "exclude_author",
    "word": "exclude_text",
}


def normalize_value(value: str) -> str:
    return " ".join((value or "").split())


def list_entries(db: Session, user: User) -> list[BlocklistEntry]:
    return (
        db.query(BlocklistEntry)
        .filter(BlocklistEntry.user_id == user.id)
        .order_by(BlocklistEntry.kind, BlocklistEntry.value)
        .all()
    )


def blocked_values(db: Session, user: User) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {kind: [] for kind in BLOCKLIST_KINDS}
    for entry in list_entries(db, user):
        grouped[entry.kind].append(entry.value)
    grouped["tag"].extend(content_limit_service.blocked_tags_of(user))
    return grouped


def _merge_unique(*groups: list[str] | None) -> list[str] | None:
    seen: set[str] = set()
    merged: list[str] = []
    for group in groups:
        for value in group or []:
            cleaned = normalize_value(value)
            key = cleaned.casefold()
            if cleaned and key not in seen:
                seen.add(key)
                merged.append(cleaned)
    return merged or None


def merged_exclusions(
    db: Session,
    user: User,
    *,
    exclude_tag: list[str] | None = None,
    exclude_fandom: list[str] | None = None,
    exclude_genre: list[str] | None = None,
    exclude_author: list[str] | None = None,
    exclude_text: list[str] | None = None,
) -> dict[str, list[str] | None]:
    """Request exclusions plus the user's blocklist, deduplicated.

    Returns the parameter names used by ``metadata_client.list_novels_metadata``.
    A list is ``None`` when it would be empty, matching the unfiltered call.
    """
    blocked = blocked_values(db, user)
    return {
        "exclude_tag": _merge_unique(exclude_tag, blocked["tag"]),
        "exclude_fandom": _merge_unique(exclude_fandom, blocked["fandom"]),
        "exclude_genre": _merge_unique(exclude_genre, blocked["genre"]),
        "exclude_author": _merge_unique(exclude_author, blocked["author"]),
        "exclude_text": _merge_unique(exclude_text, blocked["word"]),
        "content_rating": content_limit_service.allowed_ratings(user),
    }


def _names(value) -> list[str]:
    """Accept a string, a {name: ...} dict, or a list of either."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        name = value.get("name")
        return [name] if isinstance(name, str) else []
    if isinstance(value, list):
        return [name for item in value for name in _names(item)]
    return []


def item_is_blocked(item: dict, blocked: dict[str, list[str]]) -> bool:
    def hit(kind: str, candidates: list[str]) -> bool:
        wanted = {normalize_value(value).casefold() for value in blocked.get(kind, [])}
        return any(normalize_value(name).casefold() in wanted for name in candidates if name)

    if not any(blocked.values()):
        return False
    if hit("tag", _names(item.get("tags"))):
        return True
    if hit("fandom", _names(item.get("fandoms")) + _names(item.get("fandom"))):
        return True
    if hit("genre", _names(item.get("genres")) + _names(item.get("genre"))):
        return True
    author = item.get("author")
    if isinstance(author, str) and hit("author", [author]):
        return True
    words = wanted_words(blocked)
    if words:
        haystack = " ".join(
            str(item.get(key) or "") for key in ("title", "summary", "description")
        ).casefold()
        if any(word in haystack for word in words):
            return True
    return False


def wanted_words(blocked: dict[str, list[str]]) -> list[str]:
    return [normalize_value(value).casefold() for value in blocked.get("word", []) if normalize_value(value)]


def apply_blocklist(db: Session, user: User, items: list[dict]) -> list[dict]:
    """Drop items the user has blocked or that exceed their content limits.

    Works on discovery, similar, recommendation and live-search rows.
    """
    items = content_limit_service.filter_items(user, items)
    blocked = blocked_values(db, user)
    if not any(blocked.values()):
        return list(items)
    return [item for item in items if not item_is_blocked(item, blocked)]
