from uuid import uuid4
import pytest
from app.models import Chapter, Novel, ReadingProgress, ReadingHistory, ReadingRun, ReadingRunEvent, User, Library
from app.services.reading_progress_service import save_reading_progress
from app.services.reading_order import next_unread_chapter
from app.services.reading_run_service import action
from app.schemas.reading_runs import ReadingRunAction
from tests.routes.test_reader_tools import story


def endpoint(novel):return f'/reading/stories/{novel.id}/runs'


def save(db,user,chapter,percent=100,**kwargs):
    return save_reading_progress(db,user_id=user.id,chapter=chapter,position=20,percent=percent,**kwargs)


def test_start_again_archives_completion_resets_spoiler_boundary_and_fences_old_offline_saves(client,db,test_user,test_library,auth_headers):
    novel,first,last=story(db,test_library)
    old=save(db,test_user,last,operation_id='old-offline-save',expected_revision=0)
    old_key=old.reading_run_key;old_revision=old.revision
    assert db.query(ReadingRunEvent).filter_by(kind='completed').count()==1
    request=dict(expected_revision=old_revision,operation_id='reread-start',reading_run_key=old_key)
    result=client.post(endpoint(novel)+'/start',headers=auth_headers,json=request)
    assert result.status_code==200
    body=result.json();key=body['current_run_key'];assert key!=old_key and body['revision']==old_revision+1
    assert body['first_chapter_number']==first.chapter_number and body['current_progress']['chapter_number']==first.chapter_number
    assert body['current_progress']['furthest_chapter_number']==0 and body['current_progress']['furthest_percent']==0
    assert body['items'][0]['next_unread_chapter_id']==first.id
    archived=body['items'][1];assert archived['completed_at'] is not None and archived['archived_at'] is not None
    assert archived['progress']['reading_run_key']==old_key and archived['progress']['chapter_number']==last.chapter_number
    assert next_unread_chapter(db,test_user.id,novel).id==first.id
    for intent in ('automatic','reconcile','rewind','confirm_read'):
        for stale_key in (None,old_key):
            with pytest.raises(Exception) as exc:save(db,test_user,last,reading_run_key=stale_key,expected_revision=body['revision'],intent=intent)
            assert exc.value.status_code==409 and exc.value.detail['code']=='reading_run_changed'
    # A replay returns its original acknowledgement, never adopts the new run.
    replay=save(db,test_user,last,operation_id='old-offline-save',expected_revision=0)
    assert replay.reading_run_key==old_key and replay.revision==old_revision
    assert client.post(endpoint(novel)+'/start',headers=auth_headers,json=request).json()==body
    current=save(db,test_user,first,reading_run_key=key,expected_revision=body['revision'],percent=20)
    assert current.revision==body['revision']+1 and next_unread_chapter(db,test_user.id,novel).id==first.id
    current=save(db,test_user,first,reading_run_key=key,expected_revision=current.revision)
    assert next_unread_chapter(db,test_user.id,novel).id==last.id
    assert db.query(ReadingRunEvent).filter_by(kind='completed').count()==1


def test_same_day_history_is_separate_per_run_and_durable_completion_survives_rewind_and_growth(client,db,test_user,test_library,auth_headers):
    novel,first,last=story(db,test_library)
    initial=save(db,test_user,first)
    key=initial.reading_run_key
    initial=save(db,test_user,last,reading_run_key=key,expected_revision=initial.revision)
    initial=save(db,test_user,first,reading_run_key=key,expected_revision=initial.revision,percent=0,intent='rewind')
    extra=Chapter(novel_id=novel.id,chapter_number=3,title='Later source chapter',content='New source text');db.add(extra);db.commit()
    assert db.query(ReadingRunEvent).filter_by(run_key=key,kind='completed').count()==1
    body=client.post(endpoint(novel)+'/start',headers=auth_headers,json=dict(expected_revision=initial.revision,operation_id='reread')).json()
    current=save(db,test_user,first,reading_run_key=body['current_run_key'],expected_revision=body['revision'])
    points=db.query(ReadingHistory).filter_by(user_id=test_user.id,novel_id=novel.id,chapter_number=1).all()
    assert len(points)==2 and {row.reading_run_key for row in points}=={key,current.reading_run_key}
    assert db.query(ReadingRun).filter_by(run_key=key).one().completed_at is not None


def test_finish_drop_journal_are_private_bounded_and_idempotent(client,db,test_user,test_library,auth_headers):
    novel,first,last=story(db,test_library)
    progress=save(db,test_user,first,percent=25)
    request=dict(expected_revision=progress.revision,operation_id='finish-run',reading_run_key=progress.reading_run_key)
    finished=client.post(endpoint(novel)+'/finish',headers=auth_headers,json=request)
    assert finished.status_code==200 and finished.json()['current_progress']['percent']==25
    assert client.post(endpoint(novel)+'/finish',headers=auth_headers,json=request).json()==finished.json()
    drop={**request,'expected_revision':finished.json()['revision'],'operation_id':'drop-run','reason':'Pacing did not work for me.'}
    dropped=client.post(endpoint(novel)+'/drop',headers=auth_headers,json=drop)
    assert dropped.status_code==200
    run=dropped.json()['items'][0]
    assert run['status']=='abandoned' and run['completed_at'] is not None and run['abandon_reason']==drop['reason']
    page=client.get('/reading/journal?offset=0&limit=1',headers=auth_headers)
    assert page.status_code==200 and page.headers['cache-control']=='private, no-store'
    assert page.json()['total']==3 and page.json()['items'][0]['reason']==drop['reason']
    assert page.json()['items'][0]['kind']=='abandoned' and page.json()['items'][0]['inferred'] is False
    assert client.post(endpoint(novel)+'/drop',headers=auth_headers,json={**drop,'reason':'x'*501}).status_code==422
    assert client.get('/reading/journal?limit=101',headers=auth_headers).status_code==422
    assert client.get('/reading/journal').status_code==401
    other=User(username='other-run-owner',password='unused');db.add(other);db.flush()
    library=Library(user_id=other.id,name='Other');db.add(library);db.flush()
    foreign=Novel(library_id=library.id,title='Private foreign story');db.add(foreign);db.commit()
    assert client.get(endpoint(foreign),headers=auth_headers).status_code==404
    assert client.get(f'/reading/journal?novel_id={foreign.id}',headers=auth_headers).status_code==404


def test_first_explicit_start_does_not_invent_a_prior_read_and_uses_actual_first_chapter(client,db,test_user,test_library,auth_headers):
    novel,first,last=story(db,test_library)
    first.chapter_number=5;last.chapter_number=9;db.commit()
    result=client.post(endpoint(novel)+'/start',headers=auth_headers,json=dict(expected_revision=0,operation_id='first-start'))
    assert result.status_code==200
    body=result.json();assert body['total']==1 and body['items'][0]['ordinal']==1
    assert body['current_progress']['chapter_number']==5 and body['first_chapter_number']==5 and body['revision']==1
    assert db.query(ReadingRunEvent).count()==1
    assert client.post(endpoint(novel)+'/finish',headers=auth_headers,json=dict(expected_revision=1,operation_id='missing-run-key')).json()['detail']['code']=='reading_run_changed'


def test_revision_and_operation_guards_do_not_reset_or_reuse(client,db,test_user,test_library,auth_headers):
    novel,first,last=story(db,test_library)
    progress=save(db,test_user,first,percent=30,operation_id='save-key')
    request=dict(expected_revision=0,operation_id='start-stale',reading_run_key=progress.reading_run_key)
    response=client.post(endpoint(novel)+'/start',headers=auth_headers,json=request)
    assert response.status_code==409 and response.json()['detail']['current']['reading_run_key']==progress.reading_run_key
    assert db.query(ReadingRun).count()==1
    request.update(expected_revision=progress.revision,operation_id='save-key')
    assert client.post(endpoint(novel)+'/start',headers=auth_headers,json=request).json()['detail']['code']=='operation_reused'


def test_deleted_progress_row_recovers_saved_revision_and_run_identity(client,db,test_user,test_library,auth_headers):
    novel,first,last=story(db,test_library)
    progress=save(db,test_user,last)
    initial_key,revision=progress.reading_run_key,progress.revision
    # Models use a chapter cascade in older installations; simulate the lost
    # progress row while keeping the durable run and its snapshot intact.
    db.query(ReadingProgress).filter_by(id=progress.id).delete(synchronize_session=False);db.commit();db.expunge(progress)
    state=client.get(endpoint(novel),headers=auth_headers).json()
    assert state['revision']==revision and state['current_progress']['reading_run_key']==initial_key
    restored=client.get(f"/chapter/progress/{novel.id}",headers=auth_headers)
    assert restored.status_code==200 and restored.json()["revision"]==revision and restored.json()["reading_run_key"]==initial_key
    resumed=save(db,test_user,first,percent=10,reading_run_key=initial_key,expected_revision=revision)
    assert resumed.revision==revision+1 and resumed.reading_run_key==initial_key
    assert db.query(ReadingRun).count()==1 and db.query(ReadingRunEvent).filter_by(kind='completed').count()==1


def test_explicit_activity_catchup_uses_locked_current_run(client,db,test_user,test_library,auth_headers):
    from app.services.activity_service import catch_up
    novel,first,last=story(db,test_library)
    initial=save(db,test_user,last)
    started=client.post(endpoint(novel)+'/start',headers=auth_headers,json=dict(expected_revision=initial.revision,operation_id='catchup-reread')).json()
    result=catch_up(db,test_user.id,novel)
    assert result['progress_chapter_number']==last.chapter_number
    current=db.query(ReadingProgress).one()
    assert current.reading_run_key==started['current_run_key'] and current.revision==started['revision']+1
    assert current.percent==100 and db.query(ReadingRunEvent).filter_by(kind='completed').count()==2
