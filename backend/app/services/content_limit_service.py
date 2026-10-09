"""Household profiles: per-user content limits set by an administrator.

A limit is a maximum content rating (general < teen < mature < explicit)
and/or a list of blocked tags. Works whose rating is unknown are hidden from
a rating-limited profile unless ``hide_unrated`` is off. Limits are enforced
on every surface that lists or opens a catalog story: discovery, live search,
similar works, recommendations, shared shelves, the story page and imports.
"""

from fastapi import HTTPException, status

from app.models.user import User

CONTENT_RATINGS = ("general", "teen", "mature", "explicit")
NOT_RATED = "not_rated"
_ALIASES = {
    "general audiences": "general",
    "teen and up audiences": "teen",
    "not rated": NOT_RATED,
}
BLOCKED_TAG_LIMIT = 50
RESTRICTED_MESSAGE = "This story is outside the content limits of your profile."


def normalize_rating(value: str | None) -> str | None:
    """One of CONTENT_RATINGS or ``not_rated``; None when blank or unknown."""
    key = " ".join(str(value or "").strip().lower().split())
    key = _ALIASES.get(key, key)
    return key if key in CONTENT_RATINGS or key == NOT_RATED else None


def rating_of(item: dict) -> str:
    return normalize_rating(item.get("content_rating")) or NOT_RATED


def clean_blocked_tags(tags: list[str] | None) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for tag in tags or []:
        value = " ".join(str(tag or "").split())[:60]
        if value and value.casefold() not in seen:
            seen.add(value.casefold())
            cleaned.append(value)
    return cleaned[:BLOCKED_TAG_LIMIT]


def blocked_tags_of(user: User) -> list[str]:
    return clean_blocked_tags(user.blocked_tags if isinstance(user.blocked_tags, list) else [])


def is_limited(user: User) -> bool:
    return bool(user.max_content_rating) or bool(blocked_tags_of(user))


def allowed_ratings(user: User) -> list[str] | None:
    """Ratings this profile may see, for the metadata server's filter; None when unlimited."""
    maximum = normalize_rating(user.max_content_rating)
    if maximum not in CONTENT_RATINGS:
        return None
    allowed = list(CONTENT_RATINGS[: CONTENT_RATINGS.index(maximum) + 1])
    if not user.hide_unrated:
        allowed.append(NOT_RATED)
    return allowed


def describe(user: User) -> dict:
    return {
        "max_content_rating": normalize_rating(user.max_content_rating) if user.max_content_rating else None,
        "hide_unrated": bool(user.hide_unrated),
        "blocked_tags": blocked_tags_of(user),
        "limited": is_limited(user),
    }


def _names(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        name = value.get("name")
        return [name] if isinstance(name, str) else []
    if isinstance(value, list):
        return [name for item in value for name in _names(item)]
    return []


def item_allowed(user: User, item: dict) -> bool:
    allowed = allowed_ratings(user)
    if allowed is not None and rating_of(item) not in allowed:
        return False
    blocked = {tag.casefold() for tag in blocked_tags_of(user)}
    if blocked:
        names = _names(item.get("tags")) + _names(item.get("genres")) + _names(item.get("genre"))
        if any(" ".join(name.split()).casefold() in blocked for name in names):
            return False
    return True


def filter_items(user: User, items: list[dict]) -> list[dict]:
    if not is_limited(user):
        return list(items)
    return [item for item in items if item_allowed(user, item)]


def restricted() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=RESTRICTED_MESSAGE)


async def story_allowed(user: User, metadata_id: int | None) -> bool:
    """Whether a catalog story may be shown to this profile.

    A story the catalog cannot describe counts as unrated, so a limited
    profile fails closed when the metadata server is unreachable.
    """
    if not is_limited(user):
        return True
    from app.services import metadata_client

    metadata: dict = {}
    if metadata_id:
        try:
            metadata = await metadata_client.get_novel_metadata(int(metadata_id)) or {}
        except Exception:
            metadata = {}
    return item_allowed(user, metadata if isinstance(metadata, dict) else {})


async def ensure_story_allowed(user: User, metadata_id: int | None) -> None:
    if not await story_allowed(user, metadata_id):
        raise restricted()
