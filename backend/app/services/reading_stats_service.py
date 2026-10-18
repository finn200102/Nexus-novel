"""Reading stats v1: per-day reading time, words and finished chapters, plus summaries.

Time is recorded by the reader heartbeat (see POST /stats/reading-time). The
server clamps every heartbeat so a client cannot inflate the numbers.
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.novel import Novel, novel_tag
from app.models.library import Library
from app.models.reading_session import ReadingSessionDaily
from app.models.tag import Tag
from app.services.reading_activity_service import tracking_enabled,utc_today

MAX_SECONDS_PER_CALL = 90
MAX_WORDS_PER_SECOND = 10  # roughly 600 wpm, faster than any real reader
STREAK_MIN_SECONDS = 300  # a day counts toward the streak with at least 5 minutes
FINISHED_PERCENT = 95
TOP_LIMIT = 5
TAG_LIMIT = 10
RANGE_DAYS = {"week": 7, "month": 30, "year": 365, "all": None}


def clamp_reading_time(seconds: int, words: int) -> tuple[int, int]:
    """Return the (seconds, words) that will be stored for one heartbeat."""
    seconds = min(max(int(seconds), 0), MAX_SECONDS_PER_CALL)
    words = min(max(int(words), 0), seconds * MAX_WORDS_PER_SECOND)
    return seconds, words


def compute_streaks(qualifying_days: set[date], today: date) -> tuple[int, int]:
    """Return (current, longest) streak lengths in days.

    The current streak may end yesterday: today not having qualified yet does
    not break it. Gaps reset it. Longest is over all days in the set.
    """
    start = today if today in qualifying_days else today - timedelta(days=1)
    current = 0
    day = start
    while day in qualifying_days:
        current += 1
        day -= timedelta(days=1)

    longest = 0
    run = 0
    previous = None
    for day in sorted(qualifying_days):
        run = run + 1 if previous is not None and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
    return current, longest


def _upsert_daily(db: Session, *, user_id: int, novel_id: int, day: date,
                  seconds: int = 0, words: int = 0, chapters: int = 0) -> ReadingSessionDaily:
    """Add to the day's row for this novel, creating it if needed. Does not commit."""
    row = db.query(ReadingSessionDaily).filter(
        ReadingSessionDaily.user_id == user_id,
        ReadingSessionDaily.novel_id == novel_id,
        ReadingSessionDaily.day == day,
    ).first()
    if not row:
        row = ReadingSessionDaily(user_id=user_id, novel_id=novel_id, day=day, seconds=0, words=0, chapters_finished=0)
        db.add(row)
    row.seconds = (row.seconds or 0) + seconds
    row.words = (row.words or 0) + words
    row.chapters_finished = (row.chapters_finished or 0) + chapters
    return row


def record_reading_time(db: Session, *, user_id: int, novel_id: int, seconds: int, words: int,
                        today: date | None = None) -> int:
    """Store one clamped heartbeat. Returns the seconds actually recorded."""
    if not tracking_enabled(db,user_id):
        db.commit()
        return 0
    seconds, words = clamp_reading_time(seconds, words)
    if seconds == 0:
        return 0
    _upsert_daily(db, user_id=user_id, novel_id=novel_id, day=today or utc_today(), seconds=seconds, words=words)
    db.commit()
    return seconds


def record_progress_crossing(db: Session, *, user_id: int, novel_id: int, chapter_number: int,
                             previous_chapter: int | None, previous_percent: float, percent: float,
                             today: date | None = None) -> None:
    """Count a chapter as finished when progress first reaches FINISHED_PERCENT. Does not commit."""
    if not tracking_enabled(db,user_id):return
    crossed = (
        previous_chapter == chapter_number
        and previous_percent < FINISHED_PERCENT
        and percent >= FINISHED_PERCENT
    )
    if crossed:
        _upsert_daily(db, user_id=user_id, novel_id=novel_id, day=today or utc_today(), chapters=1)


def _window_start(range_name: str, today: date) -> date | None:
    days = RANGE_DAYS[range_name]
    return None if days is None else today - timedelta(days=days - 1)


def get_summary(db: Session, *, user_id: int, range_name: str, today: date | None = None, calendar_start: date | None = None) -> dict:
    if range_name not in RANGE_DAYS:
        raise ValueError(f"unknown range: {range_name}")
    today = today or utc_today()
    start = calendar_start or _window_start(range_name, today)

    measurement_query = db.query(ReadingSessionDaily).join(Novel, Novel.id == ReadingSessionDaily.novel_id).join(
        Library, Library.id == Novel.library_id).filter(
        ReadingSessionDaily.user_id == user_id, Library.user_id == user_id, ReadingSessionDaily.day <= today)
    if calendar_start is not None:measurement_query=measurement_query.filter(ReadingSessionDaily.day>=calendar_start)
    all_rows=measurement_query.all()
    per_day_seconds: dict[date, int] = defaultdict(int)
    for row in all_rows:
        per_day_seconds[row.day] += row.seconds or 0
    qualifying = {day for day, seconds in per_day_seconds.items() if seconds >= STREAK_MIN_SECONDS}
    current_streak, longest_streak = compute_streaks(qualifying, today)

    rows = [row for row in all_rows if row.day <= today and (start is None or row.day >= start)]
    novel_ids = sorted({row.novel_id for row in rows})

    titles, sites, tags = {}, {}, defaultdict(int)
    if novel_ids:
        for novel in db.query(Novel).filter(Novel.id.in_(novel_ids)).all():
            titles[novel.id] = novel.title
            sites[novel.id] = novel.novel_site or "unknown"
        for novel_id, tag_name in db.query(novel_tag.c.novel_id, Tag.name).join(
            Tag, Tag.id == novel_tag.c.tag_id
        ).filter(novel_tag.c.novel_id.in_(novel_ids)).all():
            tags[(novel_id, tag_name)] = 1

    daily: dict[date, dict] = {}
    per_novel: dict[int, dict] = defaultdict(lambda: {"seconds": 0, "words": 0})
    per_site: dict[str, int] = defaultdict(int)
    per_tag: dict[str, int] = defaultdict(int)
    totals = {"seconds": 0, "words": 0, "chapters_finished": 0}
    for row in rows:
        day = daily.setdefault(row.day, {"seconds": 0, "words": 0, "chapters_finished": 0})
        for bucket in (day, totals):
            bucket["seconds"] += row.seconds or 0
            bucket["words"] += row.words or 0
            bucket["chapters_finished"] += row.chapters_finished or 0
        per_novel[row.novel_id]["seconds"] += row.seconds or 0
        per_novel[row.novel_id]["words"] += row.words or 0
        per_site[sites.get(row.novel_id, "unknown")] += row.seconds or 0
    for novel_id, tag_name in tags:
        if novel_id in per_novel:
            per_tag[tag_name] += per_novel[novel_id]["seconds"]

    first_day = min(daily) if daily else today
    series_start = start or first_day
    daily_series = []
    day = series_start
    while day <= today:
        values = daily.get(day, {"seconds": 0, "words": 0, "chapters_finished": 0})
        daily_series.append({"date": day.isoformat(), **values})
        day += timedelta(days=1)

    completions = _completion_summary(db, user_id=user_id, start=start, today=today)

    top_stories = sorted(
        ({"novel_id": nid, "title": titles.get(nid, "Unknown story"), **vals} for nid, vals in per_novel.items()),
        key=lambda item: item["seconds"], reverse=True,
    )[:TOP_LIMIT]
    return {
        "range": range_name,
        "start": start.isoformat() if start else None,
        "end": today.isoformat(),
        "totals": {**totals, **completions["totals"]},
        "completion_history": completions["history"],
        "daily": daily_series,
        "streak": {"current": current_streak, "longest": longest_streak, "min_seconds": STREAK_MIN_SECONDS},
        "top_stories": top_stories,
        "by_site": sorted(
            ({"site": site, "seconds": seconds} for site, seconds in per_site.items()),
            key=lambda item: item["seconds"], reverse=True,
        ),
        "by_tag": sorted(
            ({"tag": tag, "seconds": seconds} for tag, seconds in per_tag.items()),
            key=lambda item: item["seconds"], reverse=True,
        )[:TAG_LIMIT],
    }


def _completion_ordinal(local_ordinal: int, snapshot) -> int:
    """An imported run keeps its original first-read/reread meaning."""
    portable = snapshot.get("_portable_ordinal") if isinstance(snapshot, dict) else None
    return portable if type(portable) is int and portable > 0 else local_ordinal


def _completion_events(db,user_id):
    from app.models.reading_run import ReadingRun, ReadingRunEvent
    from app.services.reading_continuity_service import completion_rows,work_key
    legacy = db.query(ReadingRunEvent.run_key, ReadingRunEvent.novel_id,
        ReadingRunEvent.occurred_at, ReadingRunEvent.inferred, ReadingRun.ordinal, ReadingRun.progress_snapshot).join(
        ReadingRun, (ReadingRun.run_key == ReadingRunEvent.run_key)
        & (ReadingRun.user_id == ReadingRunEvent.user_id)
        & (ReadingRun.novel_id == ReadingRunEvent.novel_id)).join(
        Novel, Novel.id == ReadingRunEvent.novel_id).join(Library, Library.id == Novel.library_id).filter(
        ReadingRunEvent.user_id == user_id, ReadingRunEvent.kind == "completed", Library.user_id == user_id, ReadingRun.continuity_key.is_(None)).all()
    identities={novel_id:work_key(db,user_id,novel_id) for novel_id in {row[1] for row in legacy}}
    compatible=[(*row[:5],{**(row[5] or {}),'_continuity_work_key':identities[row[1]]}) for row in legacy]
    return completion_rows(db,user_id) + compatible


def _completion_summary(db: Session, *, user_id: int, start: date | None, today: date, events=None) -> dict:
    """Count immutable completion facts; undated history is all-time only."""
    if events is None:events=_completion_events(db,user_id)
    # Prefer known exact dates over an earlier inferred fact for the same run.
    # Date sorting also makes contradictory duplicate imports deterministic.
    events=sorted(events,key=lambda event:(bool(event[3] or event[2] is None),event[2] or datetime.max))
    seen, stories = set(), set()
    runs_finished = rereads_finished = undated_runs = 0
    for run_key, novel_id, occurred_at, inferred, ordinal, snapshot in events:
        if run_key in seen:
            continue
        seen.add(run_key)
        undated = inferred or occurred_at is None
        if undated:
            undated_runs += 1
            if start is not None:
                continue
        else:
            completed_day = occurred_at.date()
            if completed_day > today or (start is not None and completed_day < start):
                continue
        stories.add(snapshot.get("_continuity_work_key",novel_id) if isinstance(snapshot,dict) else novel_id)
        runs_finished += 1
        rereads_finished += int(_completion_ordinal(ordinal, snapshot) > 1)
    return {"totals": {"stories_finished": len(stories), "reading_runs_finished": runs_finished,
        "rereads_finished": rereads_finished}, "history": {"undated_runs": undated_runs,
        "undated_runs_included": start is None}}


def _stories_finished(db: Session, *, user_id: int, start: date | None) -> int:
    """Retain the existing helper contract, using durable events rather than position."""
    return _completion_summary(db, user_id=user_id, start=start, today=date.today())["totals"]["stories_finished"]
