"""Identity fences reject stale addresses without disturbing originals."""
 # Imported fixtures use the established dependency-injection names.
# ruff: noqa: F811
from uuid import uuid4
import pytest
from sqlalchemy import func, select
from fastapi import HTTPException
from app.models import Chapter, Library
from app.models.chapter_manifest import ChapterManifestState
from app.services import chapter_identity_service as identity
from app.services.chapter_document import from_text
from tests.routes.test_reader_tools import story
from tests.routes.conftest import db, test_user, test_library  # noqa: F401


@pytest.fixture
def original(db,test_library):
    novel,chapter,_=story(db,test_library)
    chapter.content='Original private words';chapter.document=from_text(chapter.content)
    db.commit();db.refresh(chapter)
    return novel,chapter


def captured(chapter):
    return {f'expected_{key}':value for key,value in identity.identity(chapter).items()} | {'expected_content_version':identity.source_version(chapter)}


def test_database_identity_and_current_wire_are_complete(db,test_user,original):
    novel,chapter=original
    value=captured(chapter)
    assert value['expected_chapter_key']==chapter.chapter_key
    assert len(value['expected_manifest_epoch'])==36 and value['expected_manifest_revision'].isdigit()
    assert identity.check_write(db,test_user.id,chapter,**value,require_content_version=True)['source_version']==chapter.document['content_version']


@pytest.mark.parametrize('field,value,code',[('expected_chapter_key',str(uuid4()),'chapter_manifest_changed'),
    ('expected_manifest_epoch',str(uuid4()),'chapter_manifest_changed'),('expected_manifest_revision','999999','chapter_manifest_changed'),
    ('expected_content_version','f'*64,'content_changed'),('expected_manifest_epoch',None,'chapter_identity_required')])
def test_wrong_captured_identity_never_accepts_an_ordinal(db,test_user,original,field,value,code):
    _,chapter=original;expected=captured(chapter);expected[field]=value
    with pytest.raises(HTTPException) as caught:identity.check_write(db,test_user.id,chapter,**expected,require_content_version=True)
    assert caught.value.status_code==409 and caught.value.detail['code']==code
    db.rollback()
    assert chapter.content=='Original private words'


def test_legacy_writes_only_before_reviewed_topology_requirement(db,test_user,original):
    novel,chapter=original
    assert identity.check_write(db,test_user.id,chapter)['chapter_key']==chapter.chapter_key
    state=db.get(ChapterManifestState,novel.id);state.identity_required=True;db.commit()
    with pytest.raises(HTTPException) as caught:identity.check_write(db,test_user.id,chapter)
    assert caught.value.detail['code']=='chapter_identity_required'
    db.rollback()
    assert identity.check_write(db,test_user.id,chapter,**captured(chapter),require_content_version=True)


def test_missing_current_source_version_is_not_replaced_with_locator_version(db,test_user,original):
    _,chapter=original;value=captured(chapter);value.pop('expected_content_version')
    with pytest.raises(HTTPException) as caught:identity.check_write(db,test_user.id,chapter,**value,require_content_version=True)
    assert caught.value.detail['code']=='chapter_identity_required'


def test_archives_are_hidden_from_rows_projections_joins_counts_and_subqueries(db,test_user,original):
    novel,chapter=original;key=chapter.chapter_key;chapter.archived=True;db.commit()
    assert db.query(Chapter).filter_by(id=chapter.id).all()==[]
    assert db.query(Chapter.id).filter(Chapter.id==chapter.id).all()==[]
    assert db.query(func.count(Chapter.id)).filter(Chapter.id==chapter.id).scalar()==0
    assert db.query(Library.id).join(Library.novels).join(Chapter).filter(Chapter.id==chapter.id).all()==[]
    subset=select(Chapter.id).where(Chapter.id==chapter.id).subquery()
    assert db.query(subset.c.id).all()==[]
    archived=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(id=chapter.id).one()
    assert archived.chapter_key==key and archived.content=='Original private words'
    with pytest.raises(HTTPException) as caught:identity.guard_read(db,archived,key)
    assert caught.value.detail['code']=='chapter_archived'


def test_strong_checkpoints_are_current_run_identity_and_version_specific(db,test_user,original):
    from app.services.reading_progress_service import save_reading_progress
    from app.services.reading_checkpoint_service import checkpoint_rows
    from app.services.reading_run_service import current_run
    from app.models import ReadingHistory,ChapterReadReceipt
    novel,chapter=original
    version_a=chapter.document['content_version']
    saved=save_reading_progress(db,user_id=test_user.id,chapter=chapter,position=0,percent=100,content_version=version_a)
    run=current_run(db,test_user.id,novel.id,saved)
    relation=checkpoint_rows(db,test_user.id,novel.id,saved,run,strong_identity=True)
    rows=db.query(relation).all()
    assert len(rows)==1 and rows[0].chapter_key==chapter.chapter_key and rows[0].content_version==version_a and rows[0].max_percent==100
    # A lifetime read of B does not prove B was finished in this run.
    chapter.content='Revised original version B';chapter.document=from_text(chapter.content)
    version_b=chapter.document['content_version']
    db.add(ChapterReadReceipt(user_id=test_user.id,chapter_id=chapter.id,content_version=version_b,completed=True,requires_review=False));db.commit()
    saved=save_reading_progress(db,user_id=test_user.id,chapter=chapter,position=0,percent=50,content_version=version_b)
    history=db.query(ReadingHistory).filter_by(user_id=test_user.id,novel_id=novel.id,chapter_key=chapter.chapter_key).one()
    assert history.max_percent==100 and history.verified_percent==50 and history.verified_content_version==version_b
    relation=checkpoint_rows(db,test_user.id,novel.id,saved,run,strong_identity=True)
    assert all(row.max_percent==50 and row.content_version==version_b for row in db.query(relation))
    # An old tab without a captured version cannot stamp the server's new text.
    saved=save_reading_progress(db,user_id=test_user.id,chapter=chapter,position=0,percent=100)
    relation=checkpoint_rows(db,test_user.id,novel.id,saved,run,strong_identity=True)
    assert saved.source_content_version is None
    assert all(row.max_percent==50 for row in db.query(relation))
    saved=save_reading_progress(db,user_id=test_user.id,chapter=chapter,position=0,percent=100,content_version=version_b,intent='confirm_read')
    relation=checkpoint_rows(db,test_user.id,novel.id,saved,run,strong_identity=True)
    assert all(row.max_percent==100 and row.content_version==version_b for row in db.query(relation))


def test_inferred_old_completion_is_not_promoted_by_new_partial_position(db,test_user,original):
    from app.models import ReadingHistory
    from app.services.reading_progress_service import save_reading_progress
    from app.services.reading_checkpoint_service import checkpoint_rows
    from app.services.reading_run_service import current_run
    novel,chapter=original;version=chapter.document['content_version']
    saved=save_reading_progress(db,user_id=test_user.id,chapter=chapter,position=0,percent=0,content_version=version)
    run=current_run(db,test_user.id,novel.id,saved)
    history=db.query(ReadingHistory).filter_by(novel_id=novel.id,chapter_key=chapter.chapter_key).one()
    history.max_percent=100;history.identity_inferred=True;history.verified_percent=0;history.verified_content_version=None;db.commit()
    saved=save_reading_progress(db,user_id=test_user.id,chapter=chapter,position=0,percent=50,content_version=version)
    assert history.identity_inferred and history.max_percent==100
    relation=checkpoint_rows(db,test_user.id,novel.id,saved,run,strong_identity=True)
    assert all(row.max_percent==50 for row in db.query(relation))
