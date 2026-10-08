"""Short, human "why this" reasons for a recommended story.

Reasons come only from data Nexus already holds: the user's personal ratings,
the source story's tags and genres, and author names. Each reason is a
sentence the UI can show as-is. At most ``MAX_REASONS`` are returned.
"""

from dataclasses import dataclass, field

MAX_REASONS = 3
RATED_THRESHOLD = 4
MAX_SHARED_TERMS = 3


@dataclass
class ReasonSource:
    title: str
    terms: list[str] = field(default_factory=list)
    author: str | None = None
    rating: int | None = None
    # Terms that produced this candidate in the search, when the caller knows them.
    via_terms: list[str] = field(default_factory=list)


def _names(values) -> list[str]:
    names: list[str] = []
    for value in values or []:
        if isinstance(value, dict):
            value = value.get("name")
        if isinstance(value, str) and value.strip():
            names.append(value.strip())
    return names


def terms_of(item: dict) -> list[str]:
    """Tag and genre names of a metadata row, in source order, without duplicates."""
    seen: set[str] = set()
    ordered: list[str] = []
    for name in _names(item.get("tags")) + _names(item.get("genres")):
        if name.casefold() not in seen:
            seen.add(name.casefold())
            ordered.append(name)
    return ordered


def build_reasons(candidate: dict, sources: list[ReasonSource]) -> list[str]:
    candidate_terms = {name.casefold(): name for name in terms_of(candidate)}
    candidate_author = (candidate.get("author") or "").strip().casefold()
    reasons: list[str] = []

    rated = sorted(
        (source for source in sources if source.rating and source.rating >= RATED_THRESHOLD),
        key=lambda source: (-(source.rating or 0), source.title.casefold()),
    )
    for source in rated[:1]:
        reasons.append(f"Similar to {source.title} you rated {source.rating}★")

    shared: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        if name.casefold() not in seen:
            seen.add(name.casefold())
            shared.append(name)

    for source in sources:
        # Terms the search used to find this candidate are shared by definition.
        for term in source.via_terms:
            add(term)
        for term in source.terms:
            if term.casefold() in candidate_terms:
                add(candidate_terms[term.casefold()])
    if shared:
        reasons.append(f"Shares tags: {', '.join(shared[:MAX_SHARED_TERMS])}")

    if candidate_author and any((source.author or "").strip().casefold() == candidate_author for source in sources):
        author = candidate.get("author") or ""
        reasons.append(f"Same author: {author}")

    if not reasons and sources:
        reasons.append(f"Similar to {sources[0].title}")
    return reasons[:MAX_REASONS]
