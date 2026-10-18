"""Independent migration safety cases against private synthetic source material."""
# Imported pytest fixtures intentionally use dependency injection names.
# ruff: noqa: F811
from copy import deepcopy
from datetime import datetime
from uuid import uuid4

import pytest

from app.models import Chapter, Novel, ReadingProgress, ReadingRun, ReadingHistory
from app.models.chapter import ContentStatus
from app.models.chapter_read_receipt import ChapterReadReceipt
from app.models.reading_annotation import ReadingAnnotation
from app.services.chapter_document import from_html
from app.services.reading_run_service import progress_view
from tests.routes.conftest import db, test_user, test_library, client, auth_headers  # noqa: F401
from tests.database.test_reading_run_migration import run_engine  # noqa: F401


def seed_pair(db, test_user, test_library):
    source = Novel(library_id=test_library.id, title='Private original edition', site='royalroad',
        url='https://www.royalroad.com/fiction/991', metadata_id=991)
    target = Novel(library_id=test_library.id, title='Private replacement edition', site='scribblehub',
        url='https://www.scribblehub.com/series/992', metadata_id=992)
    db.add_all([source, target]); db.flush()
    chapters = [[], []]
    for index, (left, right) in enumerate([(3, 10), (7, 20), (11, 30)]):
        document = from_html(f'<p>Original {index} 😀 <em>unmodified</em> prose.</p><hr><p>Secret {index} remains exact.</p>')
        for novel, number, collection in [(source, left, chapters[0]), (target, right, chapters[1])]:
            chapter = Chapter(novel_id=novel.id, chapter_number=number, title=f'Distinct scene {index}',
                content=document['plain_text'], document=deepcopy(document), content_status=ContentStatus.PRESENT,
                site_chapter_id=100 + index)
            db.add(chapter); db.flush(); db.refresh(chapter); collection.append(chapter)
    run = ReadingRun(user_id=test_user.id, novel_id=source.id, run_key=str(uuid4()), ordinal=1,
        status='active', requires_run_key=True, progress_snapshot={})
    db.add(run); db.flush()
    chapter = chapters[0][1]
    block = chapter.document['blocks'][0]
    progress = ReadingProgress(user_id=test_user.id, novel_id=source.id, chapter_id=chapter.id,
        chapter_number=7, percent=45, position=120, furthest_chapter_number=7, furthest_percent=60,
        revision=4, reading_run_key=run.run_key, block_id=block['id'], text_offset=11,
        text_quote='😀', locator_content_version=chapter.document['content_version'])
    db.add(progress); db.flush(); run.progress_snapshot = progress_view(progress)
    first = chapters[0][0]
    from app.services.chapter_identity_service import manifest_state
    topology=manifest_state(db,source.id)
    progress.chapter_key=chapter.chapter_key;progress.furthest_chapter_key=chapter.chapter_key
    progress.source_content_version=chapter.document['content_version'];progress.furthest_content_version=chapter.document['content_version']
    progress.manifest_epoch=topology.manifest_epoch;progress.manifest_revision=str(topology.revision)
    db.add_all([ReadingHistory(user_id=test_user.id, novel_id=source.id, chapter_number=3, reading_run_key=run.run_key,
        reading_date=datetime(2025,2,14), max_percent=100),
        ReadingHistory(user_id=test_user.id, novel_id=source.id, chapter_number=7, reading_run_key=run.run_key,
        reading_date=datetime(2025,2,15), max_percent=45)])
    db.add(ChapterReadReceipt(user_id=test_user.id, chapter_id=first.id,
        content_version=first.document['content_version'], completed=True, requires_review=False))
    # A lifetime future receipt from an earlier reading must not widen this run.
    future = chapters[0][2]
    db.add(ChapterReadReceipt(user_id=test_user.id, chapter_id=future.id,
        content_version=future.document['content_version'], completed=True, requires_review=False))
    db.add(ReadingAnnotation(user_id=test_user.id, novel_id=source.id, chapter_id=chapter.id,
        annotation_type='highlight', block_id=block['id'], text_offset=11, text_quote='😀', quote='😀',
        locator_content_version=chapter.document['content_version'], percent=45, note='Private literal note'))
    db.flush()
    for history in db.query(ReadingHistory).filter_by(novel_id=source.id):
        original=next(row for row in chapters[0] if row.chapter_number==history.chapter_number)
        history.chapter_key=original.chapter_key;history.verified_content_version=original.document['content_version'];history.verified_percent=history.max_percent
    run.progress_snapshot=progress_view(progress)
    db.commit()
    return source, target, chapters, run, progress


@pytest.fixture
def migration_pair(db, test_user, test_library):
    return seed_pair(db, test_user, test_library)

def preview(client, headers, pair, **extra):
    source, target, *_ = pair
    return client.post('/reader/source-migrations/preview', headers=headers,
        json={'source_novel_id':source.id, 'target_novel_id':target.id, **extra})


def apply_preview(client, headers, pair, reviewed, operation=None, **extra):
    source, target, *_ = pair
    return client.post('/reader/source-migrations/apply', headers=headers,
        json={'source_novel_id':source.id, 'target_novel_id':target.id,
            'review_token':reviewed['review_token'], 'operation_id':operation or str(uuid4()), **extra})


@pytest.mark.parametrize('foreign_side', ['source', 'target'])
def test_foreign_and_household_collaborator_cannot_preview_private_copy(client, db, test_user, auth_headers,
                                                                      migration_pair, foreign_side):
    from app.models import User, Library
    from app.models.shelf import Shelf, ShelfNovel
    from tests.auth_helpers import bearer_headers
    source, target, *_ = migration_pair
    foreign = User(username=f'migration-foreign-{foreign_side}', password='unused')
    db.add(foreign); db.flush()
    library = Library(user_id=foreign.id, name='Private foreign stories')
    db.add(library); db.flush()
    novel = Novel(library_id=library.id, title='Foreign secret title')
    db.add(novel); db.flush()
    db.add(Chapter(novel_id=novel.id, chapter_number=1, title='Foreign secret chapter', content='Never leak this'))
    shelf = Shelf(user_id=foreign.id, name='Household references')
    db.add(shelf); db.flush(); db.add(ShelfNovel(shelf_id=shelf.id, novel_id=novel.id, position=0))
    db.commit()
    shared = client.put(f'/shelves/{shelf.id}/shares/{test_user.id}', headers=bearer_headers(foreign.id),
        json={'permission':'collaborate'})
    assert shared.status_code == 200
    ids = {'source_novel_id':source.id, 'target_novel_id':target.id}
    ids[f'{foreign_side}_novel_id'] = novel.id
    for path in ['preview', 'apply']:
        payload = {**ids}
        if path == 'apply':
            payload.update(review_token='0'*64, operation_id=str(uuid4()))
        response = client.post(f'/reader/source-migrations/{path}', headers=auth_headers, json=payload)
        assert response.status_code == 404
        assert 'Foreign secret' not in response.text and 'Never leak this' not in response.text


@pytest.mark.parametrize('mutation', ['source_progress', 'source_content', 'target_content', 'source_annotation'])
def test_reviewed_preview_cannot_apply_after_inputs_change(client, db, auth_headers, migration_pair, mutation):
    result = preview(client, auth_headers, migration_pair)
    assert result.status_code == 200, result.text
    reviewed = result.json()
    source, target, chapters, run, progress = migration_pair
    if mutation == 'source_progress':
        progress.revision += 1
        progress.percent = 47
    elif mutation == 'source_content':
        chapters[0][1].document = from_html('<p>Source changed after review.</p>')
        chapters[0][1].content = 'Source changed after review.'
    elif mutation == 'target_content':
        chapters[1][1].document = from_html('<p>Target changed after review.</p>')
        chapters[1][1].content = 'Target changed after review.'
    else:
        db.query(ReadingAnnotation).filter_by(novel_id=source.id).one().note = 'Edited after review'
    db.commit()
    response = apply_preview(client, auth_headers, migration_pair, reviewed)
    assert response.status_code == 409, response.text
    assert not db.query(ReadingProgress).filter_by(novel_id=target.id).count()
    assert not db.query(ReadingRun).filter_by(novel_id=target.id).count()


def test_cross_site_integer_ids_and_generic_titles_are_not_identity_evidence(client, db, auth_headers, migration_pair):
    _, _, chapters, *_ = migration_pair
    for chapter in chapters[0] + chapters[1]:
        chapter.title = 'Chapter 1'
    for index, chapter in enumerate(chapters[1]):
        chapter.document = from_html(f'<p>Unrelated replacement text {index}.</p>')
        chapter.content = chapter.document['plain_text']
    db.commit()
    response = preview(client, auth_headers, migration_pair)
    assert response.status_code == 200, response.text
    result = response.json()
    assert all(item['selected_target_chapter_id'] is None for item in result['items'])
    assert all(item['decision'] != 'matched' for item in result['items'])
    assert not result['can_apply']


def test_duplicate_exact_content_requires_review_instead_of_first_match(client, db, auth_headers, migration_pair):
    _, _, chapters, *_ = migration_pair
    for chapter in chapters[0] + chapters[1]:
        chapter.title = 'Chapter 1'
    chapters[1][1].document = deepcopy(chapters[1][0].document)
    chapters[1][1].content = chapters[1][0].content
    db.commit()
    response = preview(client, auth_headers, migration_pair)
    assert response.status_code == 200, response.text
    item = next(row for row in response.json()['items'] if row['source_chapter_id'] == chapters[0][0].id)
    assert item['decision'] == 'ambiguous'
    assert item['selected_target_chapter_id'] is None
    assert {row['target_chapter_id'] for row in item['candidates']} == {chapters[1][0].id, chapters[1][1].id}


def test_apply_preserves_originals_exact_anchor_and_private_bounded_receipts(client, db, auth_headers,
                                                                         test_user, migration_pair, monkeypatch):
    import json
    from config.settings import settings
    from tests.routes.test_reader_tools import provider
    source, target, chapters, run, original_progress = migration_pair
    original_documents = {chapter.id:deepcopy(chapter.document) for side in chapters for chapter in side}
    response = preview(client, auth_headers, migration_pair)
    assert response.status_code == 200, response.text
    assert response.json()['can_apply'], response.text
    applied = apply_preview(client, auth_headers, migration_pair, response.json())
    assert applied.status_code in (200, 201), applied.text
    progress = db.query(ReadingProgress).filter_by(user_id=test_user.id, novel_id=target.id).one()
    assert (progress.chapter_id, progress.chapter_number, progress.percent, progress.furthest_chapter_number,
        progress.furthest_percent) == (chapters[1][1].id, 20, 45, 20, 60)
    assert progress.reading_run_key != run.run_key and progress.revision >= 1
    from app.services.reading_order import next_unread_chapter
    assert next_unread_chapter(db, test_user.id, target).chapter_number == 20
    history = db.query(ReadingHistory).filter_by(novel_id=target.id).order_by(ReadingHistory.chapter_number).all()
    assert [(row.chapter_number,row.reading_date,row.max_percent) for row in history] == [
        (10,datetime(2025,2,14),100),(20,datetime(2025,2,15),45)]
    assert all(row.reading_run_key == progress.reading_run_key for row in history)
    assert (progress.block_id, progress.text_offset, progress.text_quote, progress.locator_content_version) == (
        original_progress.block_id, 11, '😀', chapters[1][1].document['content_version'])
    source_annotation = db.query(ReadingAnnotation).filter_by(novel_id=source.id).one()
    target_annotation = db.query(ReadingAnnotation).filter_by(novel_id=target.id).one()
    assert (target_annotation.note, target_annotation.quote, target_annotation.text_offset) == (
        source_annotation.note, source_annotation.quote, 11)
    receipts = db.query(ChapterReadReceipt).join(Chapter).filter(Chapter.novel_id == target.id).all()
    assert {receipt.chapter_id for receipt in receipts if receipt.completed} == {chapters[1][0].id}
    db.expire_all()
    assert all(db.get(Chapter, chapter_id).document == document for chapter_id, document in original_documents.items())
    assert db.get(ReadingProgress, original_progress.id).revision == 4
    provider_id = provider(client, auth_headers, monkeypatch)
    monkeypatch.setattr(settings, 'ANALYSIS_ENGINE_URL', 'http://analysis-fixture:8010')
    monkeypatch.setattr(settings, 'ANALYSIS_ENGINE_API_KEY', 'isolated-test-key')
    seen = []
    def answer(_db, _provider, *, prompt, **kwargs):
        seen.append(json.loads(prompt))
        return json.dumps({'answer':'Bounded', 'citations':[]}), 10, 10, 0
    monkeypatch.setattr('app.services.reader_provider.invoke', answer)
    response = client.post(f'/reader/companion/{target.id}/questions', headers=auth_headers,
        json={'provider_id':provider_id, 'question':'What is secret original prose?'})
    assert response.status_code == 200, response.text
    assert seen and {row['chapter'] for row in seen[0]['evidence']} == {10}
    assert 'Secret 2' not in json.dumps(seen) and 'Secret 1' not in json.dumps(seen)


def test_undo_and_lost_ack_replays_never_reapply_and_old_target_save_is_fenced(client, db, auth_headers,
                                                                           test_user, migration_pair):
    from app.services.reading_progress_service import save_reading_progress
    from fastapi import HTTPException
    _, target, chapters, *_ = migration_pair
    reviewed = preview(client, auth_headers, migration_pair)
    assert reviewed.status_code == 200, reviewed.text
    operation = str(uuid4())
    applied = apply_preview(client, auth_headers, migration_pair, reviewed.json(), operation)
    assert applied.status_code in (200, 201), applied.text
    record = applied.json()
    old = db.query(ReadingProgress).filter_by(novel_id=target.id).one()
    old_key, old_revision = old.reading_run_key, old.revision
    undo_operation = str(uuid4())
    undo = client.post(f"/reader/source-migrations/{record['id']}/undo", headers=auth_headers,
        json={'expected_revision':record['revision'], 'operation_id':undo_operation})
    assert undo.status_code == 200, undo.text
    assert undo.json()['status'] == 'undone'
    replay = apply_preview(client, auth_headers, migration_pair, reviewed.json(), operation)
    assert replay.status_code in (200, 201), replay.text
    replay_undo = client.post(f"/reader/source-migrations/{record['id']}/undo", headers=auth_headers,
        json={'expected_revision':record['revision'], 'operation_id':undo_operation})
    assert replay_undo.status_code == 200
    authoritative = client.get(f"/reader/source-migrations/{record['id']}", headers=auth_headers)
    assert authoritative.status_code == 200 and authoritative.json()['status'] == 'undone'
    assert not db.query(ReadingAnnotation).filter_by(novel_id=target.id).count()
    assert not db.query(ChapterReadReceipt).join(Chapter).filter(Chapter.novel_id == target.id).count()
    current = db.query(ReadingProgress).filter_by(novel_id=target.id).first()
    current_revision = current.revision if current else 0
    with pytest.raises(HTTPException) as blocked:
        save_reading_progress(db, user_id=test_user.id, chapter=chapters[1][1], position=99, percent=100,
            expected_revision=current_revision, operation_id='delayed-before-undo-save', reading_run_key=old_key,
            content_version=chapters[1][1].document['content_version'])
    assert blocked.value.status_code == 409
    assert current_revision > old_revision


@pytest.mark.parametrize('change', ['target_progress', 'target_annotation', 'source_progress'])
def test_undo_refuses_new_target_activity_but_preserves_new_source_activity(client, db, auth_headers,
                                                                          test_user, migration_pair, change):
    from app.services.reading_progress_service import save_reading_progress
    source, target, chapters, *_ = migration_pair
    reviewed = preview(client, auth_headers, migration_pair)
    assert reviewed.status_code == 200, reviewed.text
    applied = apply_preview(client, auth_headers, migration_pair, reviewed.json())
    assert applied.status_code in (200, 201), applied.text
    record = applied.json()
    if change == 'target_annotation':
        db.query(ReadingAnnotation).filter_by(novel_id=target.id).one().note = 'New private target note'
        db.commit()
    else:
        novel = source if change == 'source_progress' else target
        chapter = chapters[0][1] if change == 'source_progress' else chapters[1][1]
        progress = db.query(ReadingProgress).filter_by(novel_id=novel.id).one()
        save_reading_progress(db, user_id=test_user.id, chapter=chapter, position=800, percent=80,
            expected_revision=progress.revision, operation_id=f'new-{change}', reading_run_key=progress.reading_run_key,
            content_version=chapter.document['content_version'])
    undo = client.post(f"/reader/source-migrations/{record['id']}/undo", headers=auth_headers,
        json={'expected_revision':record['revision'], 'operation_id':str(uuid4())})
    if change == 'source_progress':
        assert undo.status_code == 200, undo.text
        db.expire_all()
        assert db.query(ReadingProgress).filter_by(novel_id=source.id).one().percent == 80
    else:
        assert undo.status_code == 409, undo.text
        assert db.query(ReadingProgress).filter_by(novel_id=target.id).one().chapter_number == 20


@pytest.mark.parametrize('bad_anchor', ['split_surrogate', 'mismatched_quote'])
def test_invalid_exact_source_anchor_is_retained_without_falsely_copying(client, db, auth_headers, migration_pair, bad_anchor):
    source, _, chapters, _, progress = migration_pair
    note = db.query(ReadingAnnotation).filter_by(novel_id=source.id).one()
    if bad_anchor == 'split_surrogate':
        progress.text_offset = 12
        note.text_offset = 12
    else:
        progress.text_quote = 'Not present at this offset'
        note.text_quote = 'Not present at this offset'
    db.commit()
    response = preview(client, auth_headers, migration_pair)
    assert response.status_code == 200, response.text
    item = next(row for row in response.json()['items'] if row['source_chapter_id'] == chapters[0][1].id)
    assert item['approximate_position']
    assert item['annotations_copyable'] == 0


@pytest.mark.parametrize('kind,same_operation', [('apply', True), ('apply', False), ('undo', True), ('undo', False)])
def test_postgres_apply_and_undo_serialize_operations_without_duplicate_rows(run_engine, kind, same_operation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from fastapi import HTTPException
    from sqlalchemy.orm import sessionmaker
    from app.db_migrations import upgrade_database
    from app.models import User, Library
    from app.models.source_migration import SourceMigration
    from app.schemas.source_migration import SourceMigrationPreviewInput, SourceMigrationApplyInput, SourceMigrationUndoInput
    from app.services import source_migration_service as service
    if run_engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL row lock qualification')
    upgrade_database(run_engine)
    factory = sessionmaker(bind=run_engine)
    with factory() as session:
        user = User(username='source-migration-race', password='unused')
        session.add(user); session.flush()
        library = Library(user_id=user.id, name='Private migration race')
        session.add(library); session.commit()
        source, target, *_ = seed_pair(session, user, library)
        input_value = SourceMigrationPreviewInput(source_novel_id=source.id, target_novel_id=target.id)
        reviewed = service.preview(session, user.id, input_value)
        payload = dict(source_novel_id=source.id, target_novel_id=target.id, review_token=reviewed['review_token'])
        user_id, target_id = user.id, target.id
        record_id = None
        if kind == 'undo':
            record = service.apply(session, user_id, SourceMigrationApplyInput(**payload, operation_id='setup-transfer'))
            record_id = record['id']
    barrier = Barrier(2)
    def perform(index):
        with factory() as session:
            barrier.wait()
            operation = 'shared-operation' if same_operation else f'device-operation-{index}'
            try:
                if kind == 'apply':
                    return service.apply(session, user_id, SourceMigrationApplyInput(**payload, operation_id=operation))
                return service.undo(session, user_id, record_id, SourceMigrationUndoInput(expected_revision=1, operation_id=operation))
            except HTTPException as exc:
                session.rollback()
                return exc.status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(perform, [0,1]))
    if same_operation:
        assert isinstance(results[0], dict) and results[0] == results[1]
    else:
        assert sum(isinstance(result, dict) for result in results) == 1 and 409 in results
    with factory() as session:
        assert session.query(SourceMigration).filter_by(user_id=user_id).count() == 1
        record = session.query(SourceMigration).filter_by(user_id=user_id).one()
        assert record.status == ('applied' if kind == 'apply' else 'undone')
        assert session.query(ReadingAnnotation).filter_by(novel_id=target_id).count() == (1 if kind == 'apply' else 0)
        point = session.query(ReadingProgress).filter_by(novel_id=target_id).one()
        assert point.revision == (1 if kind == 'apply' else 2)


@pytest.mark.parametrize('source_number', [0, -3])
def test_actual_zero_or_negative_source_position_is_not_an_unread_sentinel(client, db, auth_headers,
                                                                         migration_pair, source_number):
    _, _, chapters, run, progress = migration_pair
    chapter = chapters[0][0]
    chapter.chapter_number = source_number
    progress.chapter_id = chapter.id
    progress.chapter_number = source_number
    progress.chapter_key=chapter.chapter_key
    progress.furthest_chapter_key=chapter.chapter_key
    progress.source_content_version=chapter.document['content_version']
    progress.furthest_content_version=chapter.document['content_version']
    progress.furthest_chapter_number = source_number
    progress.furthest_percent = 40
    progress.percent = 40
    progress.block_id = chapter.document['blocks'][0]['id']
    progress.locator_content_version = chapter.document['content_version']
    run.progress_snapshot = progress_view(progress)
    db.commit()
    response = preview(client, auth_headers, migration_pair)
    assert response.status_code == 200, response.text
    assert response.json()['can_apply'], response.text
    applied = apply_preview(client, auth_headers, migration_pair, response.json())
    assert applied.status_code == 200, applied.text
    mapped = applied.json()['target_progress']
    assert (mapped['chapter_number'], mapped['percent'], mapped['furthest_chapter_number'], mapped['furthest_percent']) == (10, 40, 10, 40)


@pytest.mark.parametrize('side', [0,1])
def test_active_narration_blocks_review_without_touching_job(client, db, auth_headers, test_user, migration_pair, side):
    from app.models.audio_job import ChapterAudioJob
    source, target, chapters, *_ = migration_pair
    novel = source if side == 0 else target
    chapter = chapters[side][0]
    job = ChapterAudioJob(user_id=test_user.id, library_id=novel.library_id, novel_id=novel.id, chapter_id=chapter.id,
        provider_id='fixture', provider_url='http://not-contacted.invalid', provider_model='fixture', provider_voice='fixture', status='processing')
    db.add(job); db.commit()
    response = preview(client, auth_headers, migration_pair)
    assert response.status_code == 200, response.text
    assert not response.json()['can_apply'] and response.json()['review_token'] is None
    db.refresh(job)
    assert job.status == 'processing'



def test_mapping_cannot_move_furthest_before_current_position(client, db, auth_headers, migration_pair):
    _, _, chapters, run, progress = migration_pair
    progress.furthest_chapter_number = 11
    progress.furthest_percent = 60
    run.progress_snapshot = progress_view(progress)
    db.commit()
    mappings = [dict(source_chapter_id=chapters[0][0].id,target_chapter_id=chapters[1][0].id),
        dict(source_chapter_id=chapters[0][1].id,target_chapter_id=chapters[1][2].id),
        dict(source_chapter_id=chapters[0][2].id,target_chapter_id=chapters[1][1].id)]
    response = preview(client, auth_headers, migration_pair, mappings=mappings)
    assert response.status_code == 200, response.text
    assert not response.json()['can_apply']
    assert not response.json()['review_token']


def test_completed_reading_remains_one_fact_after_transfer_and_later_target_finish(client, db, auth_headers,
                                                                                 test_user, migration_pair):
    from app.schemas.reading_runs import ReadingRunAction
    from app.services import reading_run_service as runs, reading_stats_service as stats
    from app.models.reading_continuity import ReadingContinuity
    source, target, _, run, progress = migration_pair
    runs.action(db,test_user.id,source.id,ReadingRunAction(expected_revision=progress.revision,
        operation_id='finish-original-before-transfer',reading_run_key=run.run_key),'finish')
    before = stats.get_summary(db,user_id=test_user.id,range_name='all')['totals']
    group = db.query(ReadingContinuity).filter_by(user_id=test_user.id).one()
    completed_at = group.completed_at
    reviewed = preview(client,auth_headers,migration_pair)
    assert reviewed.status_code == 200 and reviewed.json()['can_apply'], reviewed.text
    applied = apply_preview(client,auth_headers,migration_pair,reviewed.json())
    assert applied.status_code == 200, applied.text
    current = db.query(ReadingProgress).filter_by(novel_id=target.id).one()
    runs.action(db,test_user.id,target.id,ReadingRunAction(expected_revision=current.revision,
        operation_id='finish-target-same-reading',reading_run_key=current.reading_run_key),'finish')
    db.refresh(group)
    assert group.completed_at == completed_at
    after = stats.get_summary(db,user_id=test_user.id,range_name='all')['totals']
    assert (after['stories_finished'],after['reading_runs_finished'],after['rereads_finished']) == (
        before['stories_finished'],before['reading_runs_finished'],before['rereads_finished']) == (1,1,0)


@pytest.mark.parametrize('mutation', ['retry_failed_job', 'edit_chapter_body', 'enqueue_new_job'])
def test_postgres_apply_fences_concurrent_jobs_and_chapter_writes(run_engine, monkeypatch, mutation):
    """Prove a real second transaction waits for migration's acquired locks."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from time import monotonic
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker
    from app.db_migrations import upgrade_database
    from app.models import User, Library
    from app.models.download_job import ChapterDownloadJob
    from app.schemas.source_migration import SourceMigrationPreviewInput, SourceMigrationApplyInput
    from app.services import source_migration_service as service
    if run_engine.dialect.name != 'postgresql':
        pytest.skip('PostgreSQL row and foreign-key lock qualification')
    upgrade_database(run_engine)
    factory = sessionmaker(bind=run_engine)
    with factory() as session:
        user = User(username='migration-job-lock-race', password='unused')
        session.add(user); session.flush()
        library = Library(user_id=user.id, name='Private lock race')
        session.add(library); session.commit()
        source, target, chapters, *_ = seed_pair(session, user, library)
        chapter = chapters[0][0]
        job = ChapterDownloadJob(user_id=user.id, library_id=library.id, novel_id=source.id,
            chapter_id=chapter.id, status='failed')
        session.add(job); session.commit()
        value = SourceMigrationPreviewInput(source_novel_id=source.id, target_novel_id=target.id)
        reviewed = service.preview(session, user.id, value)
        assert reviewed['can_apply']
        payload = SourceMigrationApplyInput(**value.model_dump(), review_token=reviewed['review_token'],
            operation_id='migration-lock-race-apply')
        user_id, library_id, source_id, chapter_id, job_id = user.id, library.id, source.id, chapter.id, job.id
    locked, release, mutation_started, mutation_finished = Event(), Event(), Event(), Event()
    worker_pid = []
    original_compute = service.compute
    def pause_after_locks(*args, **kwargs):
        locked.set()
        assert release.wait(10), 'The test did not release the migration transaction'
        return original_compute(*args, **kwargs)
    monkeypatch.setattr(service, 'compute', pause_after_locks)
    def transfer():
        with factory() as session:
            return service.apply(session, user_id, payload)
    def change():
        with factory() as session:
            worker_pid.append(session.execute(text('SELECT pg_backend_pid()')).scalar_one())
            mutation_started.set()
            if mutation == 'retry_failed_job':
                session.query(ChapterDownloadJob).filter_by(id=job_id).update({'status':'queued'}, synchronize_session=False)
            elif mutation == 'edit_chapter_body':
                session.query(Chapter).filter_by(id=chapter_id).update({'content':'Changed only after migration commit'}, synchronize_session=False)
            else:
                session.add(ChapterDownloadJob(user_id=user_id, library_id=library_id, novel_id=source_id,
                    chapter_id=chapter_id, status='queued'))
                session.flush()
            session.commit()
            mutation_finished.set()
    with ThreadPoolExecutor(max_workers=2) as executor:
        applied = executor.submit(transfer)
        changed = None
        try:
            assert locked.wait(5), 'Migration failed to acquire its transaction locks'
            changed = executor.submit(change)
            assert mutation_started.wait(5)
            deadline = monotonic() + 3
            waiting = None
            while monotonic() < deadline:
                with run_engine.connect() as connection:
                    waiting = connection.execute(text('SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid'),
                        {'pid':worker_pid[0]}).scalar_one()
                if waiting == 'Lock' or mutation_finished.is_set():
                    break
                mutation_finished.wait(0.02)
            assert waiting == 'Lock', f'Concurrent {mutation} was not blocked by migration locks'
            assert not mutation_finished.is_set()
        finally:
            release.set()
        assert applied.result(timeout=10)['status'] == 'applied'
        assert changed is not None
        changed.result(timeout=10)
    assert mutation_finished.is_set()
    with factory() as session:
        if mutation == 'edit_chapter_body':
            assert session.get(Chapter, chapter_id).content == 'Changed only after migration commit'
        else:
            assert session.query(ChapterDownloadJob).filter_by(user_id=user_id, status='queued').count() == 1
