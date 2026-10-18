"""Unread chapter events keep immutable identities across reviewed addresses."""
# ruff:noqa:F811
from app.models.chapter_manifest import ChapterManifestState
from app.models.update_event import NovelUpdateEvent
from app.services.activity_service import inbox
from tests.routes.test_activity_inbox import _novel,_chapter,_event
from tests.routes.conftest import db,test_user,test_library  # noqa:F401


def test_keyed_event_follows_renumbered_original_not_replacement(db,test_user,test_library):
    novel=_novel(db,test_library)
    original=_chapter(db,novel,7)
    event=_event(db,test_user,novel,[7])
    event.details={'chapter_keys':[original.chapter_key],'chapter_numbers':[7]};db.commit()
    original.chapter_number=30;db.commit()
    replacement=_chapter(db,novel,7)
    rows=inbox(db,user_id=test_user.id,library_id=test_library.id)
    assert len(rows)==1 and rows[0]['new_chapter_count']==1 and rows[0]['first_new_chapter_number']==30
    original.archived=True;db.commit()
    assert not replacement.archived
    assert inbox(db,user_id=test_user.id,library_id=test_library.id)==[]


def test_legacy_event_only_uses_number_before_identity_review(db,test_user,test_library):
    novel=_novel(db,test_library)
    original=_chapter(db,novel,7)
    _event(db,test_user,novel,[7])
    assert inbox(db,user_id=test_user.id,library_id=test_library.id)[0]['first_new_chapter_number']==7
    original.chapter_number=30;db.commit();_chapter(db,novel,7)
    assert db.get(ChapterManifestState,novel.id).identity_required
    assert inbox(db,user_id=test_user.id,library_id=test_library.id)==[]


def test_explicit_empty_or_missing_key_never_falls_back_to_numeric_label(db,test_user,test_library):
    novel=_novel(db,test_library);_chapter(db,novel,7)
    event=_event(db,test_user,novel,[7])
    for keys in ([],['unknown-key'],'not-an-array'):
        event.details={'chapter_keys':keys,'chapter_numbers':[7]};db.commit()
        assert inbox(db,user_id=test_user.id,library_id=test_library.id)==[]


def test_sparse_signed_legacy_interval_uses_sql_not_integer_expansion(db,test_user,test_library):
    novel=_novel(db,test_library);_chapter(db,novel,-2);_chapter(db,novel,2_000_000_000)
    db.add(NovelUpdateEvent(user_id=test_user.id,novel_id=novel.id,event_type='new_chapters',
        first_chapter_number=-2_000_000_000,last_chapter_number=2_000_000_000,chapter_count=2,
        message='Legacy interval',details={},notification_visible=True));db.commit()
    rows=inbox(db,user_id=test_user.id,library_id=test_library.id)
    assert rows[0]['new_chapter_count']==2 and rows[0]['first_new_chapter_number']==-2
