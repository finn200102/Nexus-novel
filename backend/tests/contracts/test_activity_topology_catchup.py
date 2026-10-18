"""Server-selected catch-up is a weak checkpoint, never read-version evidence."""
# ruff: noqa:F811
import asyncio
from uuid import uuid4
import pytest
from fastapi import HTTPException
from app.models import ReadingProgress,ReadingHistory,ChapterReadReceipt
from app.schemas.chapter_manifest import ManifestApplyInput
from app.services import chapter_manifest_service as manifests
from app.services import chapter_identity_service as identities
from app.services.reading_progress_service import save_server_selected_position,save_reading_progress
from tests.contracts.test_chapter_manifest_reviews import case,preview  # noqa:F401
from tests.routes.conftest import db,test_user,test_library,client,auth_headers  # noqa:F401


def transformed(db,user,case):
    novel,first,last,_=case
    result=preview(db,user,novel)
    asyncio.run(manifests.apply(db,user.id,novel.id,ManifestApplyInput(review_token=result['review_token'],operation_id='review-before-catchup')))
    db.expire_all();return novel,first,last


def test_catchup_after_review_moves_position_without_read_evidence(client,db,test_user,auth_headers,case):
    novel,_,last=transformed(db,test_user,case)
    response=client.post(f'/activity/inbox/{novel.id}/caught-up',headers=auth_headers)
    assert response.status_code==200,response.text
    assert response.json()['progress_chapter_number']==30
    point=db.query(ReadingProgress).filter_by(user_id=test_user.id,novel_id=novel.id).one()
    assert point.chapter_key==last.chapter_key and point.percent==100
    assert point.source_content_version is None and point.furthest_content_version is None
    assert point.locator_content_version is None
    history=db.query(ReadingHistory).filter_by(novel_id=novel.id).one()
    assert history.max_percent==100 and history.verified_percent==0 and history.verified_content_version is None
    assert db.query(ChapterReadReceipt).count()==0
    # Ordinary bundled HTTP/service saves still require their captured source version.
    header=identities.identity(last)
    with pytest.raises(HTTPException) as caught:
        save_reading_progress(db,user_id=test_user.id,chapter=last,position=0,percent=100,
            expected_chapter_key=last.chapter_key,expected_manifest_epoch=header['manifest_epoch'],expected_manifest_revision=header['manifest_revision'],
            expected_revision=point.revision,reading_run_key=point.reading_run_key)
    assert caught.value.detail['code']=='chapter_identity_required'
    db.rollback()


@pytest.mark.parametrize('change',['revision','chapter_key','epoch','progress_revision','run'])
def test_internal_position_save_keeps_manifest_progress_and_run_fences(db,test_user,case,change):
    novel,first,last=transformed(db,test_user,case)
    header=identities.identity(last)
    kwargs=dict(user_id=test_user.id,chapter=last,position=0,percent=100,expected_revision=0,
        expected_chapter_key=last.chapter_key,expected_manifest_epoch=header['manifest_epoch'],expected_manifest_revision=header['manifest_revision'])
    if change=='revision':kwargs['expected_manifest_revision']='0'
    elif change=='chapter_key':kwargs['expected_chapter_key']=first.chapter_key
    elif change=='epoch':kwargs['expected_manifest_epoch']=str(uuid4())
    elif change=='progress_revision':kwargs['expected_revision']=999
    else:
        point=save_server_selected_position(db,**kwargs)
        # Reread run-key protection is mandatory even for server-selected catch-up.
        from app.models.reading_run import ReadingRun
        run=db.query(ReadingRun).filter_by(run_key=point.reading_run_key).one()
        run.requires_run_key=True;db.commit()
        kwargs['reading_run_key']=str(uuid4());kwargs['expected_revision']=point.revision
    with pytest.raises(HTTPException) as caught:save_server_selected_position(db,**kwargs)
    assert caught.value.status_code==409
    db.rollback();assert db.query(ChapterReadReceipt).count()==0
