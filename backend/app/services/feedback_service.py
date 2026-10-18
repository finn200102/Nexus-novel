"""Reader feedback events, implicit signal weights and the taste profile.

Everything here is per user: every query filters on ``user_id`` and nothing is
shared across accounts. Events are append-only, except ``read_time`` which keeps
one row per (user, novel) holding the running total from reading_sessions_daily.
"""

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.feedback_event import ReaderFeedbackEvent
from app.models.novel import Novel
from app.models.reading_session import ReadingSessionDaily

HALF_LIFE_DAYS = 90.0
RECENT_DROP_DAYS = 180
TASTE_LIST_SIZE = 10

KINDS = {
    "rated", "finished", "dropped", "started", "read_time", "hidden",
    "added_to_library", "removed", "opened_from_recommendation", "dismissed_recommendation",
}

# Recommendation feedback as the recommender UI sends it -> stored event kind.
RECOMMENDATION_KINDS = {
    "dismissed": "dismissed_recommendation",
    "opened": "opened_from_recommendation",
    "not_interested": "hidden",
}

# follow_state values -> event kind, recorded only when the state changes.
FOLLOW_STATE_EVENTS = {"completed": "finished", "dropped": "dropped", "reading": "started"}

IMPLICIT_WEIGHTS = {"finished": 3.0, "dropped": -2.0, "hidden": -4.0, "dismissed_recommendation": -1.0}


def decay(created_at: datetime | None, now: datetime) -> float:
    if created_at is None:
        return 1.0
    age_days = max(0.0, (_naive(now) - _naive(created_at)).total_seconds() / 86400.0)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def _naive(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def record_event(db: Session, *, user_id: int, novel_id: int, kind: str, value: float | None = None,
                 at: datetime | None = None) -> ReaderFeedbackEvent:
    """Append one event. Does not commit."""
    if kind not in KINDS:
        raise ValueError(f"unknown feedback kind: {kind}")
    event = ReaderFeedbackEvent(user_id=user_id, novel_id=novel_id, kind=kind, value=value)
    if at is not None:
        event.created_at = _naive(at)
    db.add(event)
    return event


def sync_read_time(db: Session, *, user_id: int, novel_id: int) -> float:
    """Upsert the single read_time row from reading_sessions_daily. Does not commit."""
    total = (
        db.query(func.coalesce(func.sum(ReadingSessionDaily.seconds), 0))
        .filter(ReadingSessionDaily.user_id == user_id, ReadingSessionDaily.novel_id == novel_id)
        .scalar()
    )
    row = (
        db.query(ReaderFeedbackEvent)
        .filter(ReaderFeedbackEvent.user_id == user_id, ReaderFeedbackEvent.novel_id == novel_id,
                ReaderFeedbackEvent.kind == "read_time")
        .first()
    )
    if row is None:
        row = ReaderFeedbackEvent(user_id=user_id, novel_id=novel_id, kind="read_time")
        db.add(row)
    row.value = float(total or 0)
    return row.value


def read_time_weight(seconds: float | None) -> float:
    """Log-scaled, 0 to 2: about 2 after roughly 60 hours of reading."""
    if not seconds or seconds <= 0:
        return 0.0
    hours = seconds / 3600.0
    return min(2.0, 2.0 * math.log1p(hours) / math.log1p(60.0))


def rating_weight(rating: int) -> float:
    return (rating - 3) * 2.0


def user_signal_matrix(db: Session, user, now: datetime | None = None) -> list[tuple[int, float]]:
    """Per-novel implicit weight for this user, time-decayed. Highest first."""
    now = now or _now()
    events = db.query(ReaderFeedbackEvent).filter(ReaderFeedbackEvent.user_id == user.id).all()
    by_novel: dict[int, list[ReaderFeedbackEvent]] = defaultdict(list)
    for event in events:
        by_novel[event.novel_id].append(event)

    matrix: list[tuple[int, float]] = []
    for novel_id, rows in by_novel.items():
        weight = 0.0
        finished = any(r.kind == "finished" for r in rows)
        for row in rows:
            factor = decay(row.created_at, now)
            if row.kind == "finished":
                weight += IMPLICIT_WEIGHTS["finished"] * factor
            elif row.kind == "dropped" and not finished:
                weight += IMPLICIT_WEIGHTS["dropped"] * factor
            elif row.kind in ("hidden", "dismissed_recommendation"):
                weight += IMPLICIT_WEIGHTS[row.kind] * factor
        latest_rating = max((r for r in rows if r.kind == "rated"), key=lambda r: r.created_at or datetime.min, default=None)
        if latest_rating is not None and latest_rating.value is not None:
            weight += rating_weight(int(latest_rating.value)) * decay(latest_rating.created_at, now)
        read = next((r for r in rows if r.kind == "read_time"), None)
        if read is not None:
            weight += read_time_weight(read.value)
        if abs(weight) > 1e-9:
            matrix.append((novel_id, round(weight, 4)))
    matrix.sort(key=lambda item: item[1], reverse=True)
    return matrix


def _length_range(values: list[int]) -> dict | None:
    values = sorted(v for v in values if v and v > 0)
    if len(values) < 2:
        return None

    def pct(p: float) -> int:
        idx = p * (len(values) - 1)
        lo, hi = math.floor(idx), math.ceil(idx)
        return round(values[lo] + (values[hi] - values[lo]) * (idx - lo))

    return {"p25": pct(0.25), "p75": pct(0.75), "samples": len(values)}


def taste_profile(db: Session, user, now: datetime | None = None) -> dict:
    """Compact, user-visible summary of what the reader likes, for "why we recommend"."""
    now = now or _now()
    matrix = user_signal_matrix(db, user, now)
    weights = dict(matrix)
    novel_ids = set(weights)
    novels = {}
    if novel_ids:
        rows = (
            db.query(Novel)
            .filter(Novel.id.in_(novel_ids), Novel.library.has(user_id=user.id))
            .all()
        )
        novels = {n.id: n for n in rows}

    tags: dict[str, float] = defaultdict(float)
    genres: dict[str, float] = defaultdict(float)
    sites: dict[str, float] = defaultdict(float)
    liked_lengths: list[int] = []
    for novel_id, weight in matrix:
        novel = novels.get(novel_id)
        if novel is None or weight <= 0:
            continue
        liked_lengths.append(novel.num_chapters or novel.chapter_count or 0)
        for tag in novel.tags:
            tags[tag.name] += weight
        if novel.genre is not None:
            genres[novel.genre.name] += weight
        if novel.novel_site:
            sites[novel.novel_site] += weight

    def top(bucket: dict[str, float]) -> list[dict]:
        ranked = sorted(bucket.items(), key=lambda item: item[1], reverse=True)[:TASTE_LIST_SIZE]
        return [{"name": name, "weight": round(weight, 2)} for name, weight in ranked if weight > 0]

    finished = (
        db.query(func.count(func.distinct(ReaderFeedbackEvent.novel_id)))
        .filter(ReaderFeedbackEvent.user_id == user.id, ReaderFeedbackEvent.kind == "finished")
        .scalar()
    ) or 0
    dropped = (
        db.query(func.count(func.distinct(ReaderFeedbackEvent.novel_id)))
        .filter(ReaderFeedbackEvent.user_id == user.id, ReaderFeedbackEvent.kind == "dropped")
        .scalar()
    ) or 0
    completion = round(finished / (finished + dropped), 2) if finished + dropped else None

    since = now - timedelta(days=RECENT_DROP_DAYS)
    recent_drop_rows = (
        db.query(ReaderFeedbackEvent.novel_id)
        .filter(ReaderFeedbackEvent.user_id == user.id, ReaderFeedbackEvent.kind == "dropped",
                ReaderFeedbackEvent.created_at >= since)
        .order_by(ReaderFeedbackEvent.created_at.desc())
        .limit(5)
        .all()
    )
    drop_ids = [row.novel_id for row in recent_drop_rows]
    drop_titles = {n.id: n.title for n in db.query(Novel).filter(Novel.id.in_(drop_ids), Novel.library.has(user_id=user.id)).all()} if drop_ids else {}
    recent_drops = [{"novel_id": nid, "title": drop_titles.get(nid)} for nid in drop_ids]

    return {
        "top_tags": top(tags),
        "top_fandoms": [],
        "top_genres": top(genres),
        "top_sites": top(sites),
        "length_range_chapters": _length_range(liked_lengths),
        "completion_preference": completion,
        "recent_drops": recent_drops,
        "generated_at": now.isoformat(),
    }
