"""Administrative actors are immutable accounts, never browser-supplied IDs."""
from uuid import uuid4
from unittest.mock import AsyncMock
from datetime import datetime
import pytest
from fastapi import HTTPException
from app.models.account import UserSession


def test_reader_cannot_call_any_source_review_route(client,auth_headers,monkeypatch):
    remote=AsyncMock()
    monkeypatch.setattr('app.routers.catalog_reviews.metadata_admin',remote)
    key=str(uuid4())
    for path in ('','/novels/123/head',f'/novels/123/context?capture_id={key}',f'/{key}'):
        assert client.get('/admin/source-manifest-reviews'+path,headers=auth_headers).status_code==403
    for path in ('/preview',f'/{key}/apply',f'/{key}/undo'):
        assert client.post('/admin/source-manifest-reviews'+path,headers=auth_headers,json={}).status_code==403
    remote.assert_not_awaited()


@pytest.mark.parametrize('action',['preview','apply','undo'])
def test_source_review_actor_is_injected_from_authenticated_account(client,db,test_user,auth_headers,monkeypatch,action):
    test_user.is_admin=True;db.commit()
    remote=AsyncMock(side_effect=HTTPException(418,'captured request'))
    monkeypatch.setattr('app.routers.catalog_reviews.metadata_admin',remote)
    key=str(uuid4())
    body=dict(novel_id=123,capture_id=key,expected_manifest_key=str(uuid4()),expected_revision='a'*64,
        mappings=[dict(capture_ordinal=0,chapter_key=None,new_lifecycle=True)],archive_keys=[])
    if action!='preview':body=dict(expected_revision=1,operation_id=key,review_token='prepared')
    path='/admin/source-manifest-reviews/'+('preview' if action=='preview' else f'{key}/{action}')
    assert client.post(path,json={**body,'actor_id':str(uuid4())},headers=auth_headers).status_code==422
    remote.assert_not_awaited()
    assert client.post(path,json=body,headers=auth_headers).status_code==418
    assert remote.await_args.args[2]['actor_id']==test_user.storage_id
    assert all(remote.await_args.args[2][field]==value for field,value in body.items())


@pytest.mark.parametrize('change',['demotion','revocation','disable','replacement'])
def test_administrator_response_is_rechecked_after_remote_io(client,db,test_user,auth_headers,monkeypatch,change):
    test_user.is_admin=True;db.commit()
    async def remote(*args,**kwargs):
        if change=='demotion':test_user.is_admin=False
        elif change=='disable':test_user.is_disabled=True
        elif change=='replacement':test_user.storage_id=str(uuid4())
        else:db.query(UserSession).filter_by(user_id=test_user.id).update({'revoked_at':datetime.now()})
        db.commit()
        return dict(items=[],total=0,offset=0,limit=25)
    monkeypatch.setattr('app.routers.catalog_reviews.metadata_admin',remote)
    response=client.get('/admin/source-manifest-reviews',headers=auth_headers)
    assert response.status_code==403 and 'items' not in response.json()


def test_review_paging_preserves_capture_and_current_namespace_preconditions(client,db,test_user,auth_headers,monkeypatch):
    test_user.is_admin=True;db.commit()
    remote=AsyncMock(side_effect=HTTPException(418,'captured request'))
    monkeypatch.setattr('app.routers.catalog_reviews.metadata_admin',remote)
    key=str(uuid4());manifest=str(uuid4())
    response=client.get('/admin/source-manifest-reviews/novels/123/context',headers=auth_headers,
        params=dict(capture_id=key,expected_manifest_key=manifest,expected_revision='b'*64,offset=1000,limit=1000))
    assert response.status_code==418
    assert remote.await_args.args[3]==dict(capture_id=key,expected_manifest_key=manifest,expected_revision='b'*64,offset=1000,limit=1000)
    assert client.get('/admin/source-manifest-reviews/novels/123/context',headers=auth_headers,
        params=dict(capture_id=key,limit=1001)).status_code==422


def test_admin_capture_head_is_private_and_does_not_start_source_fetches(client,db,test_user,auth_headers,monkeypatch):
    test_user.is_admin=True;db.commit()
    remote=AsyncMock(return_value=dict(protocol=1,novel_id=123,manifest_key=str(uuid4()),revision='c'*64,
        source=dict(site='fanfiction',story_id=123,source_url='https://fixture.invalid/123'),capture=None))
    monkeypatch.setattr('app.services.metadata_client._manifest_request',remote)
    response=client.get('/admin/source-manifest-reviews/novels/123/head',headers=auth_headers)
    assert response.status_code==200 and response.json()['capture'] is None
    assert response.headers['cache-control']=='private, no-store'
    assert remote.await_args.args==('/chapters/novel/123/source-manifest-head',)
