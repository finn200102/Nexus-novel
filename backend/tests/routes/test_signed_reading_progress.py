"""Actual signed chapter positions must remain distinct from unread sentinels."""
from app.models import Chapter, Novel, ReadingProgress, ReadingRun
from app.services.chapter_document import from_text
from app.services.reading_progress_service import save_reading_progress
from app.services.reading_run_service import action
from app.services.reading_order import next_unread_chapter
from app.schemas.reading_runs import ReadingRunAction


def story(db, library, numbers):
    novel = Novel(library_id=library.id, title='Signed reading fixture')
    db.add(novel); db.flush()
    rows = {}
    for number in numbers:
        document = from_text(f'Chapter {number}.')
        rows[number] = Chapter(novel_id=novel.id, chapter_number=number, title=str(number),
            content=document['plain_text'], document=document, category='story')
        db.add(rows[number])
    db.commit()
    return novel, rows


def test_negative_reread_progress_and_completed_zero_survive_rewinds(db, test_user, test_library):
    novel, chapters = story(db, test_library, [-3, -2, 0, 2])
    first = save_reading_progress(db, user_id=test_user.id, chapter=chapters[-3], position=0, percent=30)
    assert (first.furthest_chapter_number, first.furthest_percent) == (-3, 30)
    assert next_unread_chapter(db, test_user.id, novel).chapter_number == -3
    started = action(db, test_user.id, novel.id, ReadingRunAction(expected_revision=first.revision,
        reading_run_key=first.reading_run_key, operation_id='signed-start'), 'start')
    key = started['current_run_key']
    assert next_unread_chapter(db, test_user.id, novel).chapter_number == -3
    def save(number, percent):
        return save_reading_progress(db, user_id=test_user.id, chapter=chapters[number], position=0,
            percent=percent, reading_run_key=key, content_version=chapters[number].document['content_version'])
    save(-3, 94.9)
    assert next_unread_chapter(db, test_user.id, novel).chapter_number == -3
    progress = save(-3, 100)
    assert (progress.furthest_chapter_number, progress.furthest_percent) == (-3, 100)
    assert next_unread_chapter(db, test_user.id, novel).chapter_number == -2
    save(-2, 20)
    assert next_unread_chapter(db, test_user.id, novel).chapter_number == -2
    save(0, 95)
    progress = save(-3, 100)
    assert (progress.furthest_chapter_number, progress.furthest_percent) == (0, 95)
    # Finishing zero preserves its signed checkpoint; it does not mark the
    # skipped chapter -2 (only 20%) as completed in this reading run.
    assert next_unread_chapter(db, test_user.id, novel).chapter_number == -2
    action(db, test_user.id, novel.id, ReadingRunAction(expected_revision=progress.revision,
        reading_run_key=key, operation_id='signed-start-again'), 'start')
    assert next_unread_chapter(db, test_user.id, novel).chapter_number == -3


def test_legacy_completed_zero_remains_inferred_without_inventing_a_finish_date(db, test_user, test_library):
    novel, chapters = story(db, test_library, [-2, 0])
    db.add(ReadingProgress(user_id=test_user.id, novel_id=novel.id, chapter_id=chapters[0].id,
        chapter_number=0, percent=100, position=0, revision=1, furthest_chapter_number=0, furthest_percent=100))
    db.commit()
    progress = save_reading_progress(db, user_id=test_user.id, chapter=chapters[0], position=0,
        percent=100, expected_revision=1)
    run = db.query(ReadingRun).filter_by(run_key=progress.reading_run_key).one()
    assert run.completed_at is None and run.completed_at_inferred
    assert run.continuity.completed and run.continuity.completed_at is None and run.continuity.completed_at_inferred
