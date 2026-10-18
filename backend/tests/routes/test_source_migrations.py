"""Private source continuity: real transactions, no source/provider traffic."""
from copy import deepcopy
from uuid import uuid4
import pytest
from app.models import Chapter, Novel, ReadingRun, ReadingProgress
from app.models.source_migration import SourceMigration, SourceMigrationOperation
from app.models.chapter import ContentStatus
from app.services.chapter_document import from_html
from app.services.reading_progress_service import save_reading_progress
from app.services import source_migration_service as service
from app.schemas.source_migration import SourceMigrationPreviewInput, SourceMigrationApplyInput


@pytest.fixture
def pair(db,test_user,test_library):
    left=Novel(title='Original',library_id=test_library.id,site='fixture',url='https://fixture.invalid/work/1')
    right=Novel(title='Replacement',library_id=test_library.id,site='different',url='https://other.invalid/work/2')
    db.add_all([left,right]);db.flush()
    chapters=[[],[]]
    for i in range(3):
        doc=from_html(f'<p>Unique scene {i}, preserved 😀 prose.</p>')
        for bucket,novel in zip(chapters,(left,right)):
            chapter=Chapter(novel_id=novel.id,title=f'Scene titled {i}',chapter_number=i*3+2,site_chapter_id=i+1,
                document=deepcopy(doc),content=doc['plain_text'],content_status=ContentStatus.PRESENT)
            db.add(chapter);db.flush();bucket.append(chapter)
    chapter=chapters[0][1]
    point=save_reading_progress(db,user_id=test_user.id,chapter=chapter,position=33,percent=40,expected_revision=0,
        block_id=chapter.document['blocks'][0]['id'],text_offset=0,text_quote='Unique',content_version=chapter.document['content_version'])
    return left,right,chapters,point


def perform(db,user,pair):
    left,right,*_=pair
    value=SourceMigrationPreviewInput(source_novel_id=left.id,target_novel_id=right.id)
    reviewed=service.preview(db,user.id,value)
    assert reviewed['can_apply'],reviewed['warnings']
    request=SourceMigrationApplyInput(**value.model_dump(),review_token=reviewed['review_token'],operation_id=str(uuid4()))
    return service.apply(db,user.id,request),request


def test_completed_continuity_is_one_logical_read_and_reread_remains_explicit(db,test_user,pair):
    left,right,chapters,point=pair
    save_reading_progress(db,user_id=test_user.id,chapter=chapters[0][-1],position=0,percent=100,
        expected_revision=point.revision,reading_run_key=point.reading_run_key)
    record,_=perform(db,test_user,pair)
    target=db.query(ReadingProgress).filter_by(novel_id=right.id).one()
    save_reading_progress(db,user_id=test_user.id,chapter=chapters[1][-1],position=0,percent=100,
        expected_revision=target.revision,reading_run_key=target.reading_run_key)
    runs=db.query(ReadingRun).filter(ReadingRun.novel_id.in_((left.id,right.id))).all()
    assert len({row.continuity_key for row in runs})==1
    from app.services.reading_continuity_service import completion_rows
    assert len(completion_rows(db,test_user.id))==1
    assert not service.detail(db,test_user.id,record['id'])['can_undo']


def test_same_length_legacy_content_change_without_timestamp_change_invalidates_review(db,test_user,pair):
    left,right,chapters,_=pair
    chapters[0][0].document=None;db.commit()
    value=SourceMigrationPreviewInput(source_novel_id=left.id,target_novel_id=right.id)
    reviewed=service.preview(db,test_user.id,value)
    assert reviewed['can_apply']
    original=chapters[0][0].updated_at
    chapters[0][0].content=chapters[0][0].content.replace('scene','stage')
    db.flush();chapters[0][0].updated_at=original;db.commit()
    with pytest.raises(Exception) as error:
        service.apply(db,test_user.id,SourceMigrationApplyInput(**value.model_dump(),review_token=reviewed['review_token'],operation_id='stale-content'))
    assert error.value.status_code==409 and error.value.detail['code']=='review_changed'
    assert not db.query(SourceMigration).count()


def test_audit_and_receipt_survive_deleted_original_and_replay_does_not_recreate(db,test_user,pair):
    left,right,chapters,_=pair
    record,request=perform(db,test_user,pair)
    from app.services.story_audio_cleanup import stage_story_audio_removal
    stage_story_audio_removal(db,left)
    db.delete(left);db.commit();db.expire_all()
    row=db.query(SourceMigration).one()
    assert row.source_novel_id is None
    authoritative=service.detail(db,test_user.id,row.id)
    assert not authoritative['can_undo'] and authoritative['source']['title']=='Original'
    assert service.apply(db,test_user.id,request)['id']==record['id']
    assert db.query(SourceMigrationOperation).count()==1
    assert db.query(ReadingProgress).filter_by(novel_id=right.id).one().chapter_number==5


def test_long_manifest_preview_pages_without_loading_book_bodies(db,test_user,pair):
    left,right,chapters,_=pair
    rows=[]
    for index in range(19997):
        for novel in (left,right):
            rows.append(dict(novel_id=novel.id,chapter_number=100+index,title=f'Unique new event {index}',content_status=ContentStatus.MISSING,audio_status='MISSING',category='story'))
    db.bulk_insert_mappings(Chapter,rows);db.commit()
    from sqlalchemy import event
    queries=[]
    def observe(connection,cursor,statement,parameters,context,executemany):queries.append(statement)
    event.listen(db.bind,'before_cursor_execute',observe)
    try:
        page=service.preview(db,test_user.id,SourceMigrationPreviewInput(source_novel_id=left.id,target_novel_id=right.id),offset=19992,limit=8)
    finally:event.remove(db.bind,'before_cursor_execute',observe)
    assert page['total']==20000 and len(page['items'])==8 and page['can_apply']
    assert all('chapters.content AS chapters_content' not in query for query in queries)
    assert page['counts']['mapped']==20000


def test_query_parameter_work_identity_does_not_match_bare_numeric_ids(db,test_user,pair):
    left,right,chapters,_=pair
    left.site=right.site='same';left.url='https://fixture.invalid/story?id=1';right.url='https://fixture.invalid/story?id=2'
    for group in chapters:
        for item in group:item.title='Chapter 1';item.document=None;item.content=None
    db.commit()
    page=service.preview(db,test_user.id,SourceMigrationPreviewInput(source_novel_id=left.id,target_novel_id=right.id))
    assert not page['can_apply']
    assert all(not item['candidates'] for item in page['items'])


@pytest.mark.parametrize('existing_target',[False,True])
def test_copy_safe_reader_settings_only_when_absent_and_undo_exact_created_rows(db,test_user,pair,existing_target):
    from app.models import ReaderPreference,NovelPersonalData
    from app.schemas.source_migration import SourceMigrationUndoInput
    left,right,chapters,_=pair
    source_pref=ReaderPreference(user_id=test_user.id,novel_id=left.id,scope=f'story:{left.id}',revision=3,values={'layout':'paged','shortcuts':False})
    source_personal=NovelPersonalData(user_id=test_user.id,novel_id=left.id,followed_categories=['story','side_story'],notes='private original notes',rating=5,auto_download=True,keep_ahead=80,notify_when_complete=True)
    db.add_all([source_pref,source_personal])
    if existing_target:
        db.add(ReaderPreference(user_id=test_user.id,novel_id=right.id,scope=f'story:{right.id}',revision=7,values={'layout':'scroll'}))
        db.add(NovelPersonalData(user_id=test_user.id,novel_id=right.id,followed_categories=['story'],notes='existing target note',rating=2))
    db.commit()
    result,_=perform(db,test_user,pair)
    assert result['counts']['preferences_copied']==int(not existing_target)
    assert result['counts']['followed_categories_copied']==int(not existing_target)
    target_pref=db.query(ReaderPreference).filter_by(novel_id=right.id).one()
    target_personal=db.query(NovelPersonalData).filter_by(novel_id=right.id).one()
    assert target_pref.values==({'layout':'scroll'} if existing_target else {'layout':'paged','shortcuts':False})
    assert target_personal.notes==('existing target note' if existing_target else None)
    assert target_personal.rating==(2 if existing_target else None)
    assert not target_personal.auto_download and not target_personal.notify_when_complete
    service.undo(db,test_user.id,result['id'],SourceMigrationUndoInput(expected_revision=1,operation_id='undo-settings'))
    assert db.query(ReaderPreference).filter_by(novel_id=right.id).count()==int(existing_target)
    assert db.query(NovelPersonalData).filter_by(novel_id=right.id).count()==int(existing_target)
    assert db.query(ReaderPreference).filter_by(novel_id=left.id).one().values==source_pref.values


def test_undo_blank_target_can_review_and_apply_again_without_old_run_revival(db,test_user,pair):
    from app.schemas.source_migration import SourceMigrationUndoInput
    result,_=perform(db,test_user,pair)
    first_key=result['target_progress']['reading_run_key']
    undone=service.undo(db,test_user.id,result['id'],SourceMigrationUndoInput(expected_revision=1,operation_id='undo-once'))
    assert undone['target_progress']['reading_run_key']!=first_key
    second,_=perform(db,test_user,pair)
    assert second['id']!=result['id'] and second['target_progress']['reading_run_key'] not in (first_key,undone['target_progress']['reading_run_key'])
    assert second['target_progress']['revision']>undone['target_progress']['revision']


def test_legacy_plaintext_fingerprints_match_without_claiming_rich_anchors(db,test_user,pair):
    left,right,chapters,_=pair
    for group in chapters:
        for item in group:item.document=None;item.title='Chapter 1'
    db.commit()
    page=service.preview(db,test_user.id,SourceMigrationPreviewInput(source_novel_id=left.id,target_novel_id=right.id))
    assert page['can_apply']
    assert all(row['decision']=='matched' and row['candidates'][0]['evidence']==['content_fingerprint'] for row in page['items'])
    assert all(not candidate['content_equal'] for row in page['items'] for candidate in row['candidates'])
    assert next(row for row in page['items'] if row['source_chapter_number']==5)['approximate_position']


def test_account_purge_removes_only_owner_migration_audit_and_receipts(db,test_user,pair,monkeypatch):
    from app.models import User
    from app.services import account_service
    record,_=perform(db,test_user,pair)
    foreign=User(username='other-audit-owner',password='unused')
    db.add(foreign);db.flush()
    audit=SourceMigration(user_id=foreign.id,source_novel_id=None,target_novel_id=None,status='undone',revision=2,
        plan={},counts={},created_rows={},target_guard='private')
    db.add(audit);db.flush()
    db.add(SourceMigrationOperation(user_id=foreign.id,migration_id=audit.id,operation_id='foreign-receipt',fingerprint='foreign',response={'id':audit.id}))
    db.commit()
    foreign_id=foreign.id
    monkeypatch.setattr(account_service,'_user_disk_files',lambda *_:[])
    monkeypatch.setattr(account_service,'_user_download_dirs',lambda *_:[])
    account_service.delete_user_account(db,test_user)
    db.commit()
    assert db.query(SourceMigration).count()==1 and db.query(SourceMigration).one().user_id==foreign_id
    assert db.query(SourceMigrationOperation).count()==1 and db.query(SourceMigrationOperation).one().user_id==foreign_id
    assert db.get(User,foreign_id) is not None
