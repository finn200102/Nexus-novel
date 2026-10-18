"""Legacy manual creation remains usable; reviewed copies require exact topology."""
# ruff:noqa:F811
from app.models import Chapter,Library,Novel,User
from app.models.chapter_manifest import ChapterManifestState
from tests.routes.test_activity_inbox import _novel,_chapter
from tests.routes.conftest import db,test_user,test_library,client,auth_headers  # noqa:F401


def test_manual_create_requires_complete_current_revision_after_topology_change(client,db,test_user,test_library,auth_headers):
    novel=_novel(db,test_library);chapter=_chapter(db,novel,1)
    state=db.get(ChapterManifestState,novel.id)
    before=str(state.revision)
    chapter.chapter_number=-2;db.commit();db.refresh(state)
    payload={'novel_id':novel.id,'chapter_number':0,'title':'Explicit manual addition'}
    response=client.post('/chapter/',headers=auth_headers,json=payload)
    assert response.status_code==409 and response.json()['detail']['code']=='chapter_identity_required'
    response=client.post('/chapter/',headers=auth_headers,json={**payload,'expected_manifest_epoch':state.manifest_epoch,'expected_manifest_revision':before})
    assert response.status_code==409 and response.json()['detail']['code']=='chapter_manifest_changed'
    response=client.post('/chapter/',headers=auth_headers,json={**payload,'expected_manifest_epoch':state.manifest_epoch,'expected_manifest_revision':str(state.revision)})
    assert response.status_code==201,response.text
    assert response.json()['chapter_key']!=chapter.chapter_key and response.json()['chapter_number']==0
    assert db.query(Chapter).filter_by(novel_id=novel.id).count()==2


def test_manual_create_rejects_foreign_story_and_partial_manifest(client,db,test_user,test_library,auth_headers):
    foreign=User(username='Foreign chapter owner',password='x');db.add(foreign);db.flush()
    library=Library(user_id=foreign.id,name='Private');db.add(library);db.flush()
    novel=Novel(library_id=library.id,title='Foreign');db.add(novel);db.commit()
    assert client.post('/chapter/',headers=auth_headers,json={'novel_id':novel.id,'chapter_number':1}).status_code==404
    own=_novel(db,test_library)
    state=db.get(ChapterManifestState,own.id)
    response=client.post('/chapter/',headers=auth_headers,json={'novel_id':own.id,'chapter_number':1,'expected_manifest_epoch':state.manifest_epoch})
    assert response.status_code==409
    assert db.query(Chapter).count()==0


def test_manual_create_waits_for_active_owned_work(client,db,test_user,test_library,auth_headers):
    from app.models.download_job import ChapterDownloadJob
    novel=_novel(db,test_library);chapter=_chapter(db,novel,1)
    db.add(ChapterDownloadJob(user_id=test_user.id,library_id=test_library.id,novel_id=novel.id,chapter_id=chapter.id,status='retry_wait'))
    db.commit()
    response=client.post('/chapter/',headers=auth_headers,json={'novel_id':novel.id,'chapter_number':2})
    assert response.status_code==409 and response.json()['detail']['code']=='active_work'
    assert db.query(Chapter).filter_by(novel_id=novel.id).count()==1


def test_two_manual_additions_with_one_revision_serialize_to_one_new_lifecycle(db,test_user,test_library):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from sqlalchemy.orm import Session
    from fastapi import HTTPException
    from app.routers.chapter import add_chapter
    from app.schemas.chapter import ChapterCreate
    novel=_novel(db,test_library);chapter=_chapter(db,novel,1)
    chapter.chapter_number=-2;db.commit()
    state=db.get(ChapterManifestState,novel.id)
    payload=dict(novel_id=novel.id,chapter_number=0,expected_manifest_epoch=state.manifest_epoch,expected_manifest_revision=str(state.revision))
    user_id,novel_id=test_user.id,novel.id;engine=db.get_bind();db.rollback()
    barrier=Barrier(2)
    def submit():
        with Session(engine) as other:
            user=other.get(User,user_id)
            barrier.wait(timeout=10)
            try:
                added=add_chapter(ChapterCreate(**payload),other,user)
                return 201,added.chapter_key
            except HTTPException as exc:
                other.rollback();return exc.status_code,exc.detail['code']
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes=list(executor.map(lambda _:submit(),range(2)))
    assert sorted(status for status,_ in outcomes)==[201,409]
    assert next(value for status,value in outcomes if status==409)=='chapter_manifest_changed'
    db.expire_all();assert db.query(Chapter).filter_by(novel_id=novel_id).count()==2
