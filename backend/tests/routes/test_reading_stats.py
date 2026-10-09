from datetime import date, timedelta

import pytest

from app.models.chapter import Chapter
from app.models.novel import Novel
from app.models.reading_progress import ReadingProgress
from app.models.reading_session import ReadingSessionDaily
from app.models.tag import Tag
from app.models.user import User
from app.models.library import Library
from app.services import reading_stats_service as stats
from app.services.reading_progress_service import save_reading_progress

TODAY = date(2026, 10, 9)


@pytest.fixture
def novel(db, test_library):
    novel = Novel(title="Moon", library_id=test_library.id, novel_site="ao3", url="https://example.test/1")
    db.add(novel)
    db.commit()
    return novel


@pytest.fixture
def chapters(db, novel):
    rows = [Chapter(novel_id=novel.id, chapter_number=n, title=f"C{n}") for n in (1, 2)]
    db.add_all(rows)
    db.commit()
    return rows


def post_time(client, headers, novel, chapter, seconds, words=0):
    return client.post(
        "/stats/reading-time",
        json={"novel_id": novel.id, "chapter_id": chapter.id, "seconds": seconds, "words_read_estimate": words},
        headers=headers,
    )


# --- pure logic -----------------------------------------------------------

def test_heartbeat_seconds_are_capped_and_negative_ignored():
    assert stats.clamp_reading_time(500, 0) == (90, 0)
    assert stats.clamp_reading_time(-5, 100) == (0, 0)
    assert stats.clamp_reading_time(60, 10_000_000) == (60, 600)


def test_streak_today_not_yet_qualifying_keeps_yesterday_streak():
    days = {TODAY - timedelta(days=1), TODAY - timedelta(days=2)}
    assert stats.compute_streaks(days, TODAY) == (2, 2)


def test_streak_resets_on_gap_and_tracks_longest():
    days = {TODAY, TODAY - timedelta(days=1), TODAY - timedelta(days=5), TODAY - timedelta(days=6), TODAY - timedelta(days=7)}
    assert stats.compute_streaks(days, TODAY) == (2, 3)


def test_streak_is_zero_when_last_qualifying_day_is_older_than_yesterday():
    assert stats.compute_streaks({TODAY - timedelta(days=2)}, TODAY) == (0, 1)
    assert stats.compute_streaks(set(), TODAY) == (0, 0)


# --- endpoints and database -----------------------------------------------

def test_heartbeat_upserts_one_row_per_day_and_novel(client, auth_headers, db, test_user, novel, chapters):
    assert post_time(client, auth_headers, novel, chapters[0], 60, 100).status_code == 200
    response = post_time(client, auth_headers, novel, chapters[0], 90, 50)
    assert response.json() == {"recorded_seconds": 90}
    rows = db.query(ReadingSessionDaily).filter_by(user_id=test_user.id, novel_id=novel.id).all()
    assert len(rows) == 1
    assert rows[0].seconds == 150
    assert rows[0].words == 150


def test_heartbeat_for_chapter_of_other_novel_is_rejected(client, auth_headers, db, test_library, novel):
    other = Novel(title="Other", library_id=test_library.id, url="https://example.test/2")
    db.add(other)
    db.commit()
    foreign = Chapter(novel_id=other.id, chapter_number=1, title="X")
    db.add(foreign)
    db.commit()
    assert post_time(client, auth_headers, novel, foreign, 30).status_code == 404


def test_heartbeat_requires_novel_in_users_library(client, db, novel, chapters):
    stranger = User(username="stranger", password="x")
    db.add(stranger)
    db.commit()
    from tests.auth_helpers import bearer_headers
    assert post_time(client, bearer_headers(stranger.id, db), novel, chapters[0], 30).status_code == 404


def test_progress_crossing_95_counts_one_finished_chapter(db, test_user, novel, chapters):
    save_reading_progress(db, user_id=test_user.id, chapter=chapters[0], position=10, percent=50)
    save_reading_progress(db, user_id=test_user.id, chapter=chapters[0], position=20, percent=96)
    save_reading_progress(db, user_id=test_user.id, chapter=chapters[0], position=21, percent=100)
    save_reading_progress(db, user_id=test_user.id, chapter=chapters[0], position=5, percent=30)
    save_reading_progress(db, user_id=test_user.id, chapter=chapters[0], position=22, percent=97)
    rows = db.query(ReadingSessionDaily).filter_by(user_id=test_user.id).all()
    assert sum(r.chapters_finished for r in rows) == 2


def test_summary_range_filtering_and_totals(db, test_user, novel, chapters):
    stats.record_reading_time(db, user_id=test_user.id, novel_id=novel.id, seconds=60, words=100, today=TODAY)
    stats.record_reading_time(db, user_id=test_user.id, novel_id=novel.id, seconds=60, words=100,
                              today=TODAY - timedelta(days=10))
    week = stats.get_summary(db, user_id=test_user.id, range_name="week", today=TODAY)
    month = stats.get_summary(db, user_id=test_user.id, range_name="month", today=TODAY)
    everything = stats.get_summary(db, user_id=test_user.id, range_name="all", today=TODAY)
    assert week["totals"]["seconds"] == 60
    assert month["totals"]["seconds"] == 120
    assert everything["totals"]["seconds"] == 120
    assert len(week["daily"]) == 7
    assert week["daily"][-1] == {"date": "2026-10-09", "seconds": 60, "words": 100, "chapters_finished": 0}


def test_summary_breakdowns_by_site_tag_and_top_stories(db, test_user, test_library, novel):
    tag = Tag(name="slow burn")
    novel.tags.append(tag)
    other = Novel(title="Other", library_id=test_library.id, novel_site="royalroad", url="https://example.test/3")
    db.add(other)
    db.commit()
    stats.record_reading_time(db, user_id=test_user.id, novel_id=novel.id, seconds=30, words=0, today=TODAY)
    stats.record_reading_time(db, user_id=test_user.id, novel_id=other.id, seconds=90, words=0, today=TODAY)
    summary = stats.get_summary(db, user_id=test_user.id, range_name="week", today=TODAY)
    assert summary["top_stories"][0]["title"] == "Other"
    assert {row["site"]: row["seconds"] for row in summary["by_site"]} == {"ao3": 30, "royalroad": 90}
    assert summary["by_tag"] == [{"tag": "slow burn", "seconds": 30}]


def test_summary_is_scoped_to_the_requesting_user(db, test_user, novel, test_library):
    other_user = User(username="reader2", password="x")
    db.add(other_user)
    db.commit()
    stats.record_reading_time(db, user_id=other_user.id, novel_id=novel.id, seconds=600, words=0, today=TODAY)
    summary = stats.get_summary(db, user_id=test_user.id, range_name="all", today=TODAY)
    assert summary["totals"]["seconds"] == 0
    assert summary["streak"] == {"current": 0, "longest": 0, "min_seconds": 300}


def test_summary_endpoint_rejects_unknown_range(client, auth_headers):
    assert client.get("/stats/summary?range=decade", headers=auth_headers).status_code == 422
    assert client.get("/stats/summary?range=month", headers=auth_headers).status_code == 200
