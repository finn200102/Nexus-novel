"""Independent lineage invariants; no migration endpoint or external service calls."""
# Imported pytest fixtures intentionally use dependency injection names.
# ruff: noqa: F811
from datetime import date, datetime
from uuid import uuid4

import pytest

from app.models import Chapter, Novel, ReadingProgress, ReadingRun, ReadingRunEvent
from app.models.reading_continuity import ReadingContinuity
from app.schemas.reading_runs import ReadingRunAction
from app.services.chapter_document import from_html
from app.services import reading_run_service as runs, reading_stats_service as stats
from app.services.reading_progress_service import save_reading_progress
from tests.routes.conftest import db, test_user, test_library  # noqa: F401
from tests.database.test_reading_run_migration import run_engine  # noqa: F401


@pytest.fixture
def siblings(db, test_user, test_library):
    document = from_html('<p>Exact original retained for continuity qualification.</p>')
    source = Novel(library_id=test_library.id, title='Original private edition', url='nexus-local:continuity-source')
    target = Novel(library_id=test_library.id, title='Continuation edition', url='nexus-local:continuity-target')
    db.add_all([source, target]); db.flush()
    continuity = ReadingContinuity(user_id=test_user.id, continuity_key=str(uuid4()), work_key=str(uuid4()), logical_ordinal=1,
        completed=True, completed_at=datetime(2025, 2, 14, 12), completed_at_inferred=False, completion_novel_id=source.id)
    db.add(continuity); db.flush()
    members = []
    for novel, number, status in [(source, 7, 'completed'), (target, 17, 'active')]:
        chapter = Chapter(novel_id=novel.id, chapter_number=number, title=f'Final {number}', content=document['plain_text'], document=document)
        db.add(chapter); db.flush()
        run = ReadingRun(user_id=test_user.id, novel_id=novel.id, run_key=str(uuid4()), continuity_key=continuity.continuity_key,
            ordinal=1, status=status, requires_run_key=True, started_at=datetime(2024, 1, 1),
            completed_at=continuity.completed_at if status == 'completed' else None, progress_snapshot={})
        db.add(run); db.flush()
        progress = ReadingProgress(user_id=test_user.id, novel_id=novel.id, chapter_id=chapter.id, chapter_number=number,
            percent=100, furthest_chapter_number=number, furthest_percent=100, revision=1, reading_run_key=run.run_key)
        db.add(progress); db.flush()
        run.progress_snapshot = runs.progress_view(progress)
        members.append((novel, chapter, run, progress))
    db.add(ReadingRunEvent(user_id=test_user.id, novel_id=source.id, run_key=members[0][2].run_key,
        kind='completed', occurred_at=continuity.completed_at, inferred=False))
    db.commit()
    return continuity, members


def totals(db, user_id, range_name='all'):
    return stats.get_summary(db, user_id=user_id, range_name=range_name, today=date(2026, 10, 16))['totals']


def save(db, user, member, operation):
    novel, chapter, run, progress = member
    return save_reading_progress(db, user_id=user.id, chapter=chapter, position=0, percent=100,
        expected_revision=progress.revision, operation_id=operation, reading_run_key=run.run_key,
        content_version=chapter.document['content_version'])


def test_completed_source_and_later_target_autosave_count_one_logical_reading(db, test_user, siblings):
    continuity, members = siblings
    first = totals(db, test_user.id)
    assert (first['stories_finished'], first['reading_runs_finished'], first['rereads_finished']) == (1, 1, 0)
    completed = continuity.completed_at
    save(db, test_user, members[1], 'continuation-final-auto-save')
    db.refresh(continuity)
    after = totals(db, test_user.id)
    assert (after['stories_finished'], after['reading_runs_finished'], after['rereads_finished']) == (1, 1, 0)
    assert continuity.completed_at == completed
    assert totals(db, test_user.id, 'week')['reading_runs_finished'] == 0


@pytest.mark.parametrize('first_index', [0, 1])
def test_unfinished_members_can_finish_in_either_order_without_second_fact(db, test_user, siblings, first_index):
    continuity, members = siblings
    continuity.completed = False; continuity.completed_at = None; continuity.completion_novel_id = None
    db.query(ReadingRunEvent).delete()
    for _, _, run, progress in members:
        run.status = 'active'; run.completed_at = None; progress.percent = 70; progress.furthest_percent = 70
    db.commit()
    save(db, test_user, members[first_index], 'first-actual-finish')
    db.refresh(continuity)
    assert continuity.completed
    first_date = continuity.completed_at
    first_story = continuity.completion_novel_id
    save(db, test_user, members[1-first_index], 'later-other-member-finish')
    db.refresh(continuity)
    assert (continuity.completed_at, continuity.completion_novel_id) == (first_date, first_story)
    assert totals(db, test_user.id)['reading_runs_finished'] == 1


def test_new_reread_allocates_from_work_wide_logical_ordinals(db, test_user, siblings):
    continuity, members = siblings
    source, _, source_run, progress = members[0]
    target = members[1][0]
    imported = ReadingContinuity(user_id=test_user.id, continuity_key=str(uuid4()), work_key=continuity.work_key,
        logical_ordinal=7, completed=True, completed_at=datetime(2025, 3, 1), completed_at_inferred=False)
    db.add(imported); db.flush()
    db.add(ReadingRun(user_id=test_user.id, novel_id=target.id, run_key=str(uuid4()), continuity_key=imported.continuity_key,
        ordinal=2, status='completed', archived_at=datetime(2025, 3, 2), progress_snapshot={}))
    db.commit()
    response = runs.action(db, test_user.id, source.id, ReadingRunAction(expected_revision=progress.revision,
        operation_id='work-wide-new-reading', reading_run_key=source_run.run_key), 'start')
    current = db.query(ReadingRun).filter_by(run_key=response['current_run_key']).one()
    fresh = db.query(ReadingContinuity).filter_by(continuity_key=current.continuity_key).one()
    assert fresh.continuity_key != continuity.continuity_key and fresh.work_key == continuity.work_key
    assert fresh.logical_ordinal == 8 and not fresh.completed
    assert (totals(db, test_user.id)['stories_finished'], totals(db, test_user.id)['reading_runs_finished'], totals(db, test_user.id)['rereads_finished']) == (1, 2, 1)


def test_canonical_unknown_completion_date_stays_undated_despite_member_events(db, test_user, siblings):
    continuity, _ = siblings
    continuity.completed_at = None; continuity.completed_at_inferred = True
    db.commit()
    summary = stats.get_summary(db, user_id=test_user.id, range_name='all', today=date(2026, 10, 16))
    assert summary['totals']['reading_runs_finished'] == 1
    assert summary['completion_history']['undated_runs'] == 1
    assert totals(db, test_user.id, 'year')['reading_runs_finished'] == 0


def test_original_story_deletion_keeps_fact_through_active_surviving_member(db, test_user, siblings):
    continuity, members = siblings
    source = members[0][0]
    db.delete(source)
    db.commit()
    result = totals(db, test_user.id)
    assert (result['stories_finished'], result['reading_runs_finished']) == (1, 1)
    db.refresh(continuity)
    assert continuity.completed and continuity.completed_at == datetime(2025, 2, 14, 12)
    assert members[1][2].status == 'active'


def test_foreign_member_reference_cannot_expose_another_accounts_completion(db, test_user, siblings):
    from fastapi import HTTPException
    from app.models import Library, User
    from app.services.reading_continuity_service import ensure_continuity
    continuity, _ = siblings
    foreign = User(username='foreign-continuity-owner', password='unused')
    db.add(foreign); db.flush()
    library = Library(user_id=foreign.id, name='Foreign private library')
    db.add(library); db.flush()
    novel = Novel(library_id=library.id, title='Foreign private copy')
    db.add(novel); db.flush()
    corrupted_member = ReadingRun(user_id=foreign.id, novel_id=novel.id, run_key=str(uuid4()),
        continuity_key=continuity.continuity_key, ordinal=1, status='active', progress_snapshot={})
    db.add(corrupted_member); db.commit()
    assert totals(db, foreign.id)['reading_runs_finished'] == 0
    with pytest.raises(HTTPException) as blocked:
        ensure_continuity(db, corrupted_member)
    assert blocked.value.status_code == 409
    assert totals(db, test_user.id)['reading_runs_finished'] == 1


def test_legacy_unlinked_and_linked_runs_of_same_story_still_count_one_work(db, test_user, siblings):
    _, members = siblings
    source = members[0][0]
    legacy = ReadingRun(user_id=test_user.id, novel_id=source.id, run_key=str(uuid4()), ordinal=2,
        status='completed', completed_at=datetime(2025, 4, 1), progress_snapshot={})
    db.add(legacy); db.flush()
    db.add(ReadingRunEvent(user_id=test_user.id, novel_id=source.id, run_key=legacy.run_key,
        kind='completed', occurred_at=legacy.completed_at, inferred=False))
    db.commit()
    result = totals(db, test_user.id)
    assert (result['stories_finished'], result['reading_runs_finished'], result['rereads_finished']) == (1, 2, 1)


def destination(db, username):
    from app.models import User, Library
    user = User(username=username, password='unused')
    db.add(user); db.flush()
    library = Library(user_id=user.id, name='Imported private copies')
    db.add(library); db.flush()
    copies = [Novel(library_id=library.id, title=f'Imported {i}', url=f'nexus-local:{username}-{i}') for i in range(2)]
    db.add_all(copies); db.commit()
    return user, copies


def import_member(db, user, novel, exported):
    from app.schemas.user_data import ExportNovel
    from app.services.portable_reading_service import import_runs
    item = ExportNovel(url=novel.url, reading_runs=exported)
    result = import_runs(db, user, novel, item)
    db.commit()
    return result


def test_portable_siblings_share_account_scoped_fact_and_repeat_import_is_idempotent(db, test_user, siblings):
    from app.services.portable_reading_service import export_runs
    continuity, members = siblings
    exported = [export_runs(db, test_user.id, member[0].id) for member in members]
    assert exported[1][0]['status'] == 'active'
    assert exported[1][0]['continuity']['completion']['occurred_at'] == '2025-02-14T12:00:00'
    user, copies = destination(db, 'portable-siblings')
    for _ in range(2):
        for novel, rows in zip(copies, exported):
            import_member(db, user, novel, rows)
    groups = db.query(ReadingContinuity).filter_by(user_id=user.id).all()
    assert len(groups) == 1
    group = groups[0]
    assert group.continuity_key != continuity.continuity_key and group.work_key != continuity.work_key
    assert group.completed_at == continuity.completed_at
    assert db.query(ReadingRun).filter_by(user_id=user.id).count() == 2
    result = totals(db, user.id)
    assert (result['stories_finished'], result['reading_runs_finished'], result['rereads_finished']) == (1, 1, 0)


def test_active_survivor_only_export_preserves_completion_without_fabricated_member_event(db, test_user, siblings):
    from app.services.portable_reading_service import export_runs
    continuity, members = siblings
    db.delete(members[0][0]); db.commit()
    rows = export_runs(db, test_user.id, members[1][0].id)
    user, copies = destination(db, 'portable-active-survivor')
    import_member(db, user, copies[0], rows)
    restored = db.query(ReadingRun).filter_by(user_id=user.id).one()
    group = db.query(ReadingContinuity).filter_by(user_id=user.id).one()
    assert restored.status == 'active' and restored.completed_at is None
    assert not db.query(ReadingRunEvent).filter_by(user_id=user.id, kind='completed').count()
    assert group.completed and group.completed_at == continuity.completed_at
    assert totals(db, user.id)['reading_runs_finished'] == 1


def test_tampered_native_portable_fact_cannot_reassign_or_reprice_history(db, test_user, siblings):
    from app.services.portable_reading_service import export_runs
    continuity, members = siblings
    source = members[0][0]
    rows = export_runs(db, test_user.id, source.id)
    rows[0]['continuity'].update(work_key=str(uuid4()), logical_ordinal=999,
        completion={'occurred_at':'2030-01-01T00:00:00', 'inferred':True})
    before = (continuity.work_key, continuity.logical_ordinal, continuity.completed_at, continuity.completed_at_inferred)
    import_member(db, test_user, source, rows)
    db.refresh(continuity)
    assert (continuity.work_key, continuity.logical_ordinal, continuity.completed_at, continuity.completed_at_inferred) == before
    assert totals(db, test_user.id)['reading_runs_finished'] == 1


def test_later_import_same_work_does_not_split_when_target_has_native_work(db, test_user, siblings):
    from copy import deepcopy
    from app.services.portable_reading_service import export_runs
    continuity, members = siblings
    original = export_runs(db, test_user.id, members[0][0].id)
    user, copies = destination(db, 'portable-work-priority')
    local = ReadingRun(user_id=user.id, novel_id=copies[1].id, run_key=str(uuid4()), ordinal=1,
        status='active', progress_snapshot={})
    db.add(local); db.flush()
    from app.services.reading_continuity_service import ensure_continuity
    local_group = ensure_continuity(db, local)
    native_work = local_group.work_key
    db.commit()
    import_member(db, user, copies[0], original)
    first = db.query(ReadingContinuity).filter_by(user_id=user.id, completed=True).one()
    second = deepcopy(original)
    second[0]['reading_run_key'] = str(uuid4())
    second[0]['ordinal'] = 2
    second[0]['continuity']['key'] = str(uuid4())
    second[0]['continuity']['logical_ordinal'] = 2
    import_member(db, user, copies[1], second)
    imported = db.query(ReadingRun).filter_by(user_id=user.id, novel_id=copies[1].id).filter(ReadingRun.run_key != local.run_key).one()
    imported_group = db.query(ReadingContinuity).filter_by(continuity_key=imported.continuity_key).one()
    assert imported_group.work_key == first.work_key
    db.refresh(local_group)
    assert local_group.work_key == native_work
    result = totals(db, user.id)
    assert (result['stories_finished'], result['reading_runs_finished'], result['rereads_finished']) == (1, 2, 1)


@pytest.mark.parametrize('operation', ['finish', 'start'])
def test_postgres_sibling_operations_serialize_canonical_fact_and_work_ordinals(run_engine, operation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy.orm import sessionmaker
    from app.db_migrations import upgrade_database
    from app.models import User, Library
    from app.services.reading_continuity_service import complete
    if run_engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL row lock qualification')
    upgrade_database(run_engine)
    factory = sessionmaker(bind=run_engine)
    with factory() as session:
        user = User(username='concurrent-continuity', password='unused')
        session.add(user); session.flush()
        library = Library(user_id=user.id, name='Private')
        session.add(library); session.flush()
        group = ReadingContinuity(user_id=user.id, continuity_key=str(uuid4()), work_key=str(uuid4()),
            logical_ordinal=1, completed=operation == 'start', completed_at=datetime(2025, 2, 14) if operation == 'start' else None)
        session.add(group); session.flush()
        inputs = []
        for index in range(2):
            novel = Novel(library_id=library.id, title=f'Edition {index}')
            session.add(novel); session.flush()
            session.add(Chapter(novel_id=novel.id, chapter_number=3, title='First actual chapter'))
            session.flush()
            run = ReadingRun(user_id=user.id, novel_id=novel.id, run_key=str(uuid4()),
                continuity_key=group.continuity_key, ordinal=1, status='active', requires_run_key=True,
                progress_snapshot={'chapter_number':3, 'revision':1})
            session.add(run); session.flush()
            session.add(ReadingProgress(user_id=user.id, novel_id=novel.id, chapter_number=3,
                percent=50, furthest_chapter_number=3, furthest_percent=50, revision=1, reading_run_key=run.run_key))
            inputs.append((user.id, novel.id, run.run_key))
        session.commit()
        group_key, work = group.continuity_key, group.work_key
    barrier = Barrier(2)
    def perform(value):
        user_id, novel_id, key = value
        with factory() as session:
            barrier.wait()
            if operation == 'start':
                return runs.action(session, user_id, novel_id, ReadingRunAction(expected_revision=1,
                    operation_id=f'parallel-start-{novel_id}', reading_run_key=key), 'start')
            run = session.query(ReadingRun).filter_by(run_key=key).one()
            fact = complete(session, run)
            result = fact.completed_at
            session.commit()
            return result
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(perform, inputs))
    with factory() as session:
        groups = session.query(ReadingContinuity).filter_by(work_key=work).all()
        if operation == 'finish':
            assert len(groups) == 1 and groups[0].completed
            assert results[0] == results[1] == groups[0].completed_at
            assert session.query(ReadingRunEvent).filter_by(kind='completed').count() == 2
        else:
            assert sorted(group.logical_ordinal for group in groups) == [1, 2, 3]
            assert len({result['current_run_key'] for result in results}) == 2
        assert session.query(ReadingContinuity).filter_by(continuity_key=group_key).one().logical_ordinal == 1


@pytest.mark.parametrize('reverse', [False, True])
def test_full_document_import_preserves_one_work_regardless_entry_order(db, test_user, siblings, reverse):
    from app.models import Library
    from app.schemas.user_data import UserDataDocument
    from app.services.portable_reading_service import export_runs
    from app.services.user_data_service import import_user_data
    _, members = siblings
    user, copies = destination(db, f'full-document-{reverse}')
    library = db.query(Library).filter_by(id=copies[0].library_id).one()
    entries = [dict(url=copy.url, title=copy.title, reading_runs=export_runs(db, test_user.id, member[0].id))
        for copy, member in zip(copies, members)]
    if reverse:
        entries.reverse()
    document = UserDataDocument(format='nexus-user-export', version=1,
        libraries=[dict(name=library.name, novels=entries)])
    for _ in range(2):
        report = import_user_data(db, user, document)
        assert not report.get('import_jobs')
    groups = db.query(ReadingContinuity).filter_by(user_id=user.id).all()
    assert len(groups) == 1
    result = totals(db, user.id)
    assert (result['stories_finished'], result['reading_runs_finished'], result['rereads_finished']) == (1, 1, 0)
    assert groups[0].completed_at == datetime(2025, 2, 14, 12)


@pytest.mark.parametrize('legacy_first', [False, True])
def test_old_and_new_format_archives_for_same_owned_story_share_work(db, test_user, siblings, legacy_first):
    from copy import deepcopy
    from app.models import Library
    from app.schemas.user_data import UserDataDocument
    from app.services.portable_reading_service import export_runs
    from app.services.user_data_service import import_user_data
    _, members = siblings
    modern = export_runs(db, test_user.id, members[0][0].id)
    legacy = deepcopy(modern)
    legacy[0].pop('continuity')
    legacy[0]['reading_run_key'] = str(uuid4())
    legacy[0]['ordinal'] = 2
    user, copies = destination(db, f'mixed-format-{legacy_first}')
    copy = copies[0]
    library = db.query(Library).filter_by(id=copy.library_id).one()
    archives = [legacy, modern] if legacy_first else [modern, legacy]
    for rows in archives + list(reversed(archives)):
        document = UserDataDocument(format='nexus-user-export', version=1,
            libraries=[dict(name=library.name, novels=[dict(url=copy.url, reading_runs=rows)])])
        import_user_data(db, user, document)
    result = totals(db, user.id)
    assert (result['stories_finished'], result['reading_runs_finished'], result['rereads_finished']) == (1, 2, 1)
    assert db.query(ReadingRun).filter_by(user_id=user.id, novel_id=copy.id).count() == 2
