import os
from datetime import datetime

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import BaseModel
from app.models.chapter import Chapter
from app.models.library import Library
from app.models.novel import Novel
from app.models.novel_personal import NovelPersonalData
from app.models.reading_history import ReadingHistory
from app.models.reading_progress import ReadingProgress
from app.models.user import User
from app.services.reading_order import next_unread_chapter

load_dotenv()

engine = create_engine(os.environ["DATABASE_URL"])
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db():
    BaseModel.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        BaseModel.metadata.drop_all(bind=engine)


@pytest.fixture
def reader(db):
    user = User(username="reader", password="hashed_password_here")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def novel(db, reader):
    library = Library(name="Reading", user_id=reader.id)
    db.add(library)
    db.commit()
    db.refresh(library)
    novel = Novel(title="Serial", url="https://example.test/serial", library_id=library.id, novel_site="royalroad")
    db.add(novel)
    db.commit()
    db.refresh(novel)
    return novel


def _chapter(db, novel, number, *, category="story", site_id=None) -> Chapter:
    chapter = Chapter(
        novel_id=novel.id,
        chapter_number=number,
        title=f"Chapter {number}",
        category=category,
        site_chapter_id=site_id if site_id is not None else 100 + number,
    )
    db.add(chapter)
    db.commit()
    db.refresh(chapter)
    return chapter


def _progress(db, reader, novel, chapter):
    db.add(ReadingProgress(user_id=reader.id, novel_id=novel.id, chapter_id=chapter.id, chapter_number=chapter.chapter_number))
    db.commit()


def _follow(db, reader, novel, categories):
    db.add(NovelPersonalData(user_id=reader.id, novel_id=novel.id, followed_categories=categories))
    db.commit()


def test_no_progress_starts_at_first_story_chapter(db, reader, novel):
    _chapter(db, novel, 1, category="side")
    first_story = _chapter(db, novel, 2)
    _chapter(db, novel, 3)

    assert next_unread_chapter(db, reader.id, novel).id == first_story.id


def test_side_chapters_are_skipped_unless_followed(db, reader, novel):
    one = _chapter(db, novel, 1)
    side = _chapter(db, novel, 2, category="side")
    three = _chapter(db, novel, 3)
    _progress(db, reader, novel, one)

    assert next_unread_chapter(db, reader.id, novel).id == three.id

    _follow(db, reader, novel, ["story", "side"])
    assert next_unread_chapter(db, reader.id, novel).id == side.id


def test_unreviewed_renumber_does_not_infer_completion_from_legacy_position(db, reader, novel):
    first = _chapter(db, novel, 1, site_id=101)
    _chapter(db, novel, 2, site_id=102)
    five = _chapter(db, novel, 5, site_id=105)
    _progress(db, reader, novel, five)
    # The site renumbers chapter 5 to 7; the progress row still says 5.
    five.chapter_number = 7
    db.commit()
    _chapter(db, novel, 8, site_id=108)

    # The identity trigger requires reconciliation after topology changes.
    # The old unbound position supplies no completed checkpoint for earlier text.
    assert next_unread_chapter(db, reader.id, novel).id == first.id


def test_history_counts_when_progress_is_missing(db, reader, novel):
    _chapter(db, novel, 1)
    _chapter(db, novel, 2)
    three = _chapter(db, novel, 3)
    db.add(ReadingHistory(user_id=reader.id, novel_id=novel.id, chapter_number=2, reading_date=datetime(2026, 10, 1), max_percent=100))
    db.commit()

    assert next_unread_chapter(db, reader.id, novel).id == three.id


def test_deleted_chapter_does_not_turn_unbound_current_position_into_completion(db, reader, novel):
    one = _chapter(db, novel, 1)
    two = _chapter(db, novel, 2)
    _chapter(db, novel, 3)
    _progress(db, reader, novel, one)
    db.delete(two)
    db.commit()

    assert next_unread_chapter(db, reader.id, novel).id == one.id


def test_caught_up_returns_none(db, reader, novel):
    _chapter(db, novel, 1)
    last = _chapter(db, novel, 2)
    _chapter(db, novel, 3, category="side")
    _progress(db, reader, novel, last)

    assert next_unread_chapter(db, reader.id, novel) is None
