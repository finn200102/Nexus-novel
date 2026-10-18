from uuid import uuid4
from datetime import datetime
from unittest.mock import AsyncMock
from fastapi import HTTPException
import httpx
import pytest
from app.models.blocklist import BlocklistEntry
from app.models.account import UserSession


def group(seed=11):
    def member(id, title, description=None):
        return dict(edition_id=id,novel_id=id,title=title,author='Writer',description=description,
            source_url=f'https://fixture.invalid/{id}',site='royalroad',language='en',edition_kind='original',
            content_rating='general',tags=[],genres=[],fandoms=[])
    return dict(group_key=str(uuid4()),canonical_work_id=1,revision=1,title='Hidden upstream title',reviewed=True,
        edition_count=2,editions=[member(seed,'Visible edition'),member(12,'Hidden edition','spoilerword')])


def test_review_endpoints_are_admin_only(client,auth_headers,monkeypatch):
    upstream=AsyncMock()
    monkeypatch.setattr('app.routers.catalog_reviews.metadata_admin',upstream)
    for url in ('/admin/vocabulary/terms','/admin/vocabulary/raw?kind=fandom','/admin/edition-group-reviews','/admin/review-catalog/lookup?q=example'):
        assert client.get(url,headers=auth_headers).status_code==403
    upstream.assert_not_awaited()


def test_review_audit_actor_cannot_be_substituted(client,db,test_user,auth_headers,monkeypatch):
    test_user.is_admin=True; db.commit()
    upstream=AsyncMock(side_effect=HTTPException(418,detail='captured request'))
    monkeypatch.setattr('app.routers.catalog_reviews.metadata_admin',upstream)
    id=str(uuid4())
    body=dict(expected_revision=1,operation_id=str(uuid4()))
    url=f'/admin/edition-group-reviews/{id}/apply'
    assert client.post(url,headers=auth_headers,json={**body,'actor':'another account'}).status_code==422
    upstream.assert_not_awaited()
    assert client.post(url,headers=auth_headers,json=body).status_code==418
    assert upstream.await_args.args[2] == {**body,'actor':test_user.storage_id}
    aliasbody=dict(action='approve',expected_revision='a'*64,operation_id=str(uuid4()),review_token='prepared')
    assert client.post(f'/admin/vocabulary/aliases/{id}/decide',headers=auth_headers,json=aliasbody).status_code==418
    assert upstream.await_args.args[2]['actor']==test_user.storage_id


def test_admin_demotion_during_upstream_request_hides_administrative_response(client,db,test_user,auth_headers,monkeypatch):
    test_user.is_admin=True; db.commit()
    async def demoted(*args,**kwargs):
        test_user.is_admin=False;db.commit()
        return dict(items=[],total=0,offset=0,limit=50,has_more=False)
    monkeypatch.setattr('app.routers.catalog_reviews.metadata_admin',demoted)
    result=client.get('/admin/vocabulary/terms',headers=auth_headers)
    assert result.status_code==403 and 'items' not in result.json()


def test_reader_editions_filter_description_before_title_count_or_members(client,db,test_user,auth_headers,monkeypatch):
    db.add(BlocklistEntry(user_id=test_user.id,kind='word',value='spoilerword')); db.commit()
    upstream=AsyncMock(return_value=httpx.Response(200,json=group()))
    monkeypatch.setattr('app.services.catalog_read_service.metadata_client._request',upstream)
    result=client.get('/discovery/edition-groups/11',headers=auth_headers)
    assert result.status_code==200,result.text
    data=result.json()
    assert data['title']=='Visible edition' and data['edition_count']==1
    assert [item['novel_id'] for item in data['editions']]==[11]
    assert 'Hidden' not in result.text and 'spoilerword' not in result.text
    assert result.headers['cache-control']=='private, no-store'
    assert client.get('/discovery/edition-groups/12',headers=auth_headers).status_code==404


def test_reader_editions_reject_permission_changes_while_loading(client,db,test_user,auth_headers,monkeypatch):
    async def changed(*args,**kwargs):
        db.add(BlocklistEntry(user_id=test_user.id,kind='word',value='new rule')); db.commit()
        return httpx.Response(200,json=group())
    monkeypatch.setattr('app.services.catalog_read_service.metadata_client._request',changed)
    result=client.get('/discovery/edition-groups/11',headers=auth_headers)
    assert result.status_code==409 and result.json()['detail']['code']=='catalog_visibility_changed'


def test_reader_sign_out_during_request_hides_private_response(client,db,test_user,auth_headers,monkeypatch):
    async def signed_out(*args,**kwargs):
        db.query(UserSession).filter_by(user_id=test_user.id).update({'revoked_at':datetime.now()}); db.commit()
        return httpx.Response(200,json=group())
    monkeypatch.setattr('app.services.catalog_read_service.metadata_client._request',signed_out)
    result=client.get('/discovery/edition-groups/11',headers=auth_headers)
    assert result.status_code==401 and 'editions' not in result.json()


@pytest.mark.parametrize('result_key',['results','data'])
def test_both_similarity_wire_shapes_filter_actual_metadata(client,db,test_user,auth_headers,monkeypatch,result_key):
    test_user.max_content_rating='general'; db.commit()
    metadata={1:dict(title='Seed',content_rating='general',tags=[]),
        2:dict(title='Hidden',content_rating='explicit',tags=[]),
        3:dict(title='Visible',content_rating='general',tags=[])}
    async def facts(id):return metadata[id]
    monkeypatch.setattr('app.routers.discovery.metadata_client.get_novel_metadata',facts)
    upstream=AsyncMock(return_value={result_key:[dict(novel_id=2,title='Hidden'),dict(novel_id=3,title='Visible')]})
    monkeypatch.setattr('app.routers.discovery.metadata_client.get_similar_novels',upstream)
    result=client.get('/discovery/novels/1/similar',headers=auth_headers)
    assert result.status_code==200,result.text
    assert [row['novel_id'] for row in result.json()[result_key]]==[3]
    assert upstream.await_args.kwargs['seed_visibility']['content_rating']==['general']


def test_reader_vocabulary_forwards_private_limits_and_repeated_ids(client,db,test_user,auth_headers,monkeypatch):
    test_user.max_content_rating='teen'; db.commit()
    db.add(BlocklistEntry(user_id=test_user.id,kind='fandom',value='Hidden fandom')); db.commit()
    upstream=AsyncMock(return_value=httpx.Response(200,json=dict(items=[],total=0,offset=0,limit=50,has_more=False)))
    monkeypatch.setattr('app.services.catalog_read_service.metadata_client._request',upstream)
    a,b=str(uuid4()),str(uuid4())
    result=client.get(f'/discovery/vocabulary/terms?kind=character&ids={a}&ids={b}',headers=auth_headers)
    assert result.status_code==200,result.text
    params=upstream.await_args.kwargs['params']
    assert params['ids']==[a,b] and params['exclude_fandom']==['Hidden fandom']
    assert params['content_rating']==['general','teen']
    assert upstream.await_args.args[1]=='/vocabulary/reader-terms'


def test_legacy_source_decisions_cannot_bypass_reviewed_workflow(client,db,test_user,auth_headers,monkeypatch):
    test_user.is_admin=True; db.commit()
    upstream=AsyncMock()
    monkeypatch.setattr('app.routers.admin_integrations.metadata_admin',upstream)
    for action in ('approve','reject','revert'):
        result=client.post(f'/admin/integrations/merge-reviews/1/{action}',headers=auth_headers,json={})
        assert result.status_code==409 and result.json()['detail']['code']=='reviewed_workflow_required'
    upstream.assert_not_awaited()
