"""Shared cached analysis requires the same exact identities as private memory."""
# ruff: noqa: F811
from unittest.mock import AsyncMock,patch
from datetime import UTC,datetime
import pytest
from sqlalchemy import delete
from app.models import Chapter,ChapterReadReceipt,ReadingHistory
from app.services.chapter_identity_service import identity
from app.services.reading_progress_service import save_reading_progress
from tests.routes.test_discovery_story_guide import owned_scope
from tests.routes.conftest import db,test_user,test_library,client,auth_headers  # noqa: F401


def test_legacy_numeric_completions_cannot_authorize_shared_analysis(client,db,test_user,test_library,auth_headers):
    novel,_,_,_=owned_scope(db,test_user,test_library)
    db.query(ReadingHistory).filter_by(novel_id=novel.id).update({'chapter_key':None,'verified_content_version':None,'verified_percent':0})
    db.commit()
    upstream=AsyncMock()
    with patch('app.routers.discovery.metadata_client.reader_story_guide',upstream):
        response=client.get('/discovery/novels/701/story-guide',headers=auth_headers)
    assert response.status_code==200 and response.json()['safe_through_chapter'] is None
    upstream.assert_not_awaited()


def replace_first(db,novel,original):
    old_id,old_key,document=original.id,original.chapter_key,original.document
    number=original.chapter_number
    db.expunge(original)
    db.execute(delete(Chapter).where(Chapter.id==old_id).execution_options(synchronize_session=False))
    db.commit()
    replacement=Chapter(id=old_id,novel_id=novel.id,chapter_number=number,title='Same address, new lifecycle',
        content=document['plain_text'],document=document,content_status='PRESENT')
    db.add(replacement);db.commit();db.refresh(replacement)
    assert replacement.chapter_key!=old_key
    return replacement


def test_same_text_replacement_receipt_without_current_run_checkpoint_is_insufficient(client,db,test_user,test_library,auth_headers):
    novel,chapters,_,_=owned_scope(db,test_user,test_library)
    replacement=replace_first(db,novel,chapters[0])
    db.add(ChapterReadReceipt(user_id=test_user.id,chapter_id=replacement.id,content_version=replacement.document['content_version'],completed=True,requires_review=False))
    db.commit()
    upstream=AsyncMock()
    with patch('app.routers.discovery.metadata_client.reader_story_guide',upstream):
        response=client.get('/discovery/novels/701/story-guide',headers=auth_headers)
    assert response.status_code==200 and response.json()['safe_through_chapter'] is None
    upstream.assert_not_awaited()


def test_inflight_identical_replacement_is_rejected_even_after_a_real_new_read(client,db,test_user,test_library,auth_headers):
    novel,chapters,run,point=owned_scope(db,test_user,test_library)
    run_key,revision=run.run_key,point.revision
    async def upstream(*args,**kwargs):
        replacement=replace_first(db,novel,chapters[0])
        save_reading_progress(db,user_id=test_user.id,chapter=replacement,position=0,percent=100,
            content_version=replacement.document['content_version'],expected_revision=revision,reading_run_key=run_key,
            intent='confirm_read',expected_content_version=replacement.document['content_version'],
            **{f'expected_{key}':value for key,value in identity(replacement).items()})
        return {'safe_through_chapter':5,'future_wrong_lifecycle':'MUST_NOT_RETURN'}
    with patch('app.routers.discovery.metadata_client.reader_story_guide',AsyncMock(side_effect=upstream)):
        response=client.get('/discovery/novels/701/story-guide',headers=auth_headers)
    assert response.status_code==409 and response.json()['detail']['code']=='reading_scope_changed'
    assert 'MUST_NOT_RETURN' not in response.text


@pytest.mark.parametrize('mutation,expected_status',[('disabled',401),('session_revoked',401),('source_changed',409)])
def test_late_shared_guide_checks_current_account_session_and_source(client,db,test_user,test_library,auth_headers,mutation,expected_status):
    from app.models.account import UserSession
    novel,_,_,_=owned_scope(db,test_user,test_library)
    async def upstream(*args,**kwargs):
        if mutation=='disabled':test_user.is_disabled=True
        elif mutation=='session_revoked':
            for session in db.query(UserSession).filter_by(user_id=test_user.id):session.revoked_at=datetime.now(UTC).replace(tzinfo=None)
        else:novel.url='https://different-source.invalid/story/701'
        db.commit()
        return {'private_answer':'MUST_NOT_RETURN'}
    with patch('app.routers.discovery.metadata_client.reader_story_guide',AsyncMock(side_effect=upstream)):
        response=client.get('/discovery/novels/701/story-guide',headers=auth_headers)
    assert response.status_code==expected_status,response.text
    assert 'MUST_NOT_RETURN' not in response.text
