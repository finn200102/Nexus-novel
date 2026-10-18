"""Continue and download thresholds follow UUIDs through reviewed reordering."""
# ruff: noqa:F401,F811
from datetime import datetime
from uuid import uuid4
from app.models import ReadingHistory,ReadingProgress,ReadingRun
from app.services.chapter_identity_service import manifest_state
from app.services.reading_order import next_unread_chapter,last_finished_number,_current_progress_number
from tests.contracts.test_chapter_identity import original
from tests.routes.conftest import db,test_user,test_library


def test_legacy_unbound_history_cannot_skip_replacement_after_topology_review(db,test_user,original):
    novel,first=original
    state=manifest_state(db,novel.id);state.identity_required=True
    db.add(ReadingHistory(user_id=test_user.id,novel_id=novel.id,chapter_number=999,
        reading_date=datetime(2026,1,1),max_percent=100))
    db.commit()
    assert next_unread_chapter(db,test_user.id,novel).id==first.id
    assert last_finished_number(db,test_user.id,novel.id) is None


def test_modern_finished_threshold_reprojects_bound_history_to_current_label(db,test_user,original):
    novel,first=original
    run=ReadingRun(user_id=test_user.id,novel_id=novel.id,run_key=str(uuid4()),ordinal=1,status='active',
        requires_run_key=True,started_at=datetime(2026,1,1),progress_snapshot={})
    db.add(run);db.flush()
    db.add(ReadingHistory(user_id=test_user.id,novel_id=novel.id,chapter_number=9000,chapter_key=first.chapter_key,
        reading_run_key=run.run_key,reading_date=datetime(2026,1,1),max_percent=100))
    db.commit()
    assert last_finished_number(db,test_user.id,novel.id)==first.chapter_number
    first.archived=True;db.commit()
    assert last_finished_number(db,test_user.id,novel.id) is None


def test_current_uuid_never_uses_a_recycled_foreign_key_or_unreviewed_label(db,test_user,original):
    novel,first=original
    point=ReadingProgress(user_id=test_user.id,novel_id=novel.id,chapter_id=first.id,
        chapter_key=str(uuid4()),chapter_number=999,percent=100)
    assert _current_progress_number(db,point,novel.id) is None
    point.chapter_key=first.chapter_key
    assert _current_progress_number(db,point,novel.id)==first.chapter_number
    point.chapter_key=None
    manifest_state(db,novel.id).identity_required=True;db.flush()
    assert _current_progress_number(db,point,novel.id) is None
