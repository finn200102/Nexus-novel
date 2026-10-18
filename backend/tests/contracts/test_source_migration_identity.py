"""Reviewed source switching preserves immutable chapter provenance."""
# ruff: noqa: F811
from datetime import datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

from app.models import Chapter, ReadingAnnotation, ReadingHistory, ChapterReadReceipt, ReadingProgress
from app.schemas.source_migration import SourceMigrationPreviewInput, SourceMigrationApplyInput
from app.services import source_migration_service as service
from tests.routes.test_source_migrations import pair, perform  # noqa: F401
from tests.routes.conftest import db, test_user, test_library  # noqa: F401


def test_annotations_are_rebound_only_to_reviewed_target_identity(db, test_user, pair):
    left, right, chapters, point = pair
    original = chapters[0][1]
    db.add(ReadingAnnotation(user_id=test_user.id, novel_id=left.id, chapter_id=original.id,
        block_id=point.block_id, text_offset=0, text_quote='Unique', locator_content_version=point.locator_content_version,
        quote='Unique', note='Keep this private note'))
    db.commit()
    perform(db, test_user, pair)
    copied = db.query(ReadingAnnotation).filter_by(novel_id=right.id).one()
    assert copied.chapter_key == chapters[1][1].chapter_key
    assert copied.chapter_key != original.chapter_key and copied.chapter_number == chapters[1][1].chapter_number
    current = db.query(ReadingProgress).filter_by(novel_id=right.id).one()
    assert current.chapter_key == copied.chapter_key and current.manifest_epoch == right.manifest_state.manifest_epoch


def test_same_pk_text_and_title_replacement_invalidates_review(db, test_user, pair):
    left, right, chapters, _ = pair
    request = SourceMigrationPreviewInput(source_novel_id=left.id, target_novel_id=right.id)
    preview = service.preview(db, test_user.id, request)
    original = chapters[1][0]
    values = {name:getattr(original,name) for name in ('id','novel_id','chapter_number','title','content','document','site_chapter_id')}
    db.expunge(original)
    db.execute(delete(Chapter).where(Chapter.id == values['id']).execution_options(synchronize_session=False))
    db.commit()
    replacement = Chapter(**values)
    db.add(replacement)
    db.commit()
    with pytest.raises(HTTPException) as error:
        service.apply(db, test_user.id, SourceMigrationApplyInput(**request.model_dump(),
            review_token=preview['review_token'], operation_id=str(uuid4())))
    assert error.value.status_code == 409 and error.value.detail['code'] == 'review_changed'
    assert db.query(ReadingProgress).filter_by(novel_id=right.id).count() == 0


def test_unknown_numeric_history_is_retained_without_minting_read_evidence(db, test_user, pair):
    left, right, chapters, point = pair
    first = chapters[0][0]
    db.add(ReadingHistory(user_id=test_user.id, novel_id=left.id, chapter_number=first.chapter_number,
        reading_run_key=point.reading_run_key, reading_date=datetime(2024,1,1), max_percent=100))
    db.add(ChapterReadReceipt(user_id=test_user.id, chapter_id=first.id,
        content_version=first.document['content_version'], completed=True, requires_review=False))
    db.commit()
    record, _ = perform(db, test_user, pair)
    assert record['counts']['receipts_copied'] == 0
    assert db.query(ChapterReadReceipt).join(Chapter).filter(Chapter.novel_id == right.id).count() == 0
    assert db.query(ReadingHistory).filter_by(novel_id=left.id, chapter_key=None, max_percent=100).count() == 1
    assert db.query(ReadingHistory).filter_by(novel_id=right.id, chapter_key=chapters[1][0].chapter_key).count() == 0


def test_new_private_import_review_invalidates_earlier_undo_guard(db,test_user,pair):
    from app.models.import_reading_review import ImportReadingReview
    from app.schemas.source_migration import SourceMigrationUndoInput
    _,right,_,_=pair
    record,_=perform(db,test_user,pair)
    assert record['can_undo']
    db.add(ImportReadingReview(user_id=test_user.id,novel_id=right.id,fingerprint='a'*64,
        payload={'private':'Saved imported reading material'},applied_refs=[]))
    db.commit()
    assert not service.detail(db,test_user.id,record['id'])['can_undo']
    with pytest.raises(HTTPException) as error:
        service.undo(db,test_user.id,record['id'],SourceMigrationUndoInput(expected_revision=record['revision'],operation_id='undo-imported'))
    assert error.value.status_code==409 and error.value.detail['code']=='undo_changed'
    assert db.query(ImportReadingReview).one().payload=={'private':'Saved imported reading material'}
