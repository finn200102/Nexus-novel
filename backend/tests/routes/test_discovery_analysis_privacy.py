"""Analysis reads and local enrichment share the reader's current visibility."""
from datetime import datetime
from unittest.mock import AsyncMock
import pytest
from app.models.blocklist import BlocklistEntry
from app.models.account import UserSession


def request(client, headers, enqueue=False):
    path='/discovery/novels/901/analysis'+('/enqueue' if enqueue else '')
    return (client.post if enqueue else client.get)(path,headers=headers)


@pytest.mark.parametrize('enqueue',[False,True])
def test_analysis_success_uses_full_metadata_and_releases_db_before_network(client,db,auth_headers,monkeypatch,enqueue):
    calls=[]
    async def metadata(id):
        assert not db.in_transaction();calls.append('metadata')
        return dict(title='Allowed',description='Full original metadata',content_rating='general',tags=[])
    result={'queued':True,'job_id':'local-job'} if enqueue else {'state':'ready','signals':[{'value':'Visible signal'}]}
    async def operation(id, **kwargs):
        assert id==901 and not db.in_transaction();assert 'seed_visibility' in kwargs;calls.append('operation');return result
    monkeypatch.setattr('app.routers.discovery.metadata_client.get_novel_metadata',metadata)
    monkeypatch.setattr('app.routers.discovery.metadata_client.'+('enqueue_novel_analysis' if enqueue else 'get_novel_analysis'),operation)
    response=request(client,auth_headers,enqueue)
    assert response.status_code==200,response.text
    assert response.json()==result and calls==['metadata','operation']
    assert response.headers['cache-control']=='private, no-store'


@pytest.mark.parametrize('enqueue',[False,True])
@pytest.mark.parametrize('restricted_by',['rating','blocked_tag','word','fandom','author'])
def test_hidden_story_never_dispatches_analysis(client,db,test_user,auth_headers,monkeypatch,enqueue,restricted_by):
    metadata=dict(title='Allowed title',description='Sensitive secret description',content_rating='general',tags=[],fandoms=[],author='Writer')
    if restricted_by=='rating':test_user.max_content_rating='general';metadata['content_rating']='explicit'
    elif restricted_by=='blocked_tag':test_user.blocked_tags=['Forbidden'];metadata['tags']=['Forbidden']
    elif restricted_by=='word':db.add(BlocklistEntry(user_id=test_user.id,kind='word',value='secret'))
    elif restricted_by=='fandom':db.add(BlocklistEntry(user_id=test_user.id,kind='fandom',value='Hidden fandom'));metadata['fandoms']=['Hidden fandom']
    else:db.add(BlocklistEntry(user_id=test_user.id,kind='author',value='Writer'))
    db.commit()
    monkeypatch.setattr('app.routers.discovery.metadata_client.get_novel_metadata',AsyncMock(return_value=metadata))
    read=AsyncMock(return_value={'signals':['NEVER RETURN']});write=AsyncMock(return_value={'queued':True})
    monkeypatch.setattr('app.routers.discovery.metadata_client.get_novel_analysis',read)
    monkeypatch.setattr('app.routers.discovery.metadata_client.enqueue_novel_analysis',write)
    response=request(client,auth_headers,enqueue)
    assert response.status_code==(403 if restricted_by in {'rating','blocked_tag'} else 404),response.text
    read.assert_not_awaited();write.assert_not_awaited()
    assert 'NEVER RETURN' not in response.text


@pytest.mark.parametrize('enqueue',[False,True])
@pytest.mark.parametrize('phase',['metadata','analysis'])
@pytest.mark.parametrize('change',['blocklist','signout','disabled'])
def test_permission_changes_during_each_network_wait_hide_results(client,db,test_user,auth_headers,monkeypatch,enqueue,phase,change):
    async def changed():
        if change=='blocklist':db.add(BlocklistEntry(user_id=test_user.id,kind='word',value='new rule'))
        elif change=='signout':db.query(UserSession).filter_by(user_id=test_user.id).update({'revoked_at':datetime.now()})
        else:test_user.is_disabled=True
        db.commit()
    async def metadata(id):
        assert not db.in_transaction()
        if phase=='metadata':await changed()
        return dict(title='Visible',content_rating='general',tags=[])
    async def operation(id, **kwargs):
        assert not db.in_transaction()
        if phase=='analysis':await changed()
        return {'signals':['PRIVATE RESPONSE'],'queued':True}
    upstream=AsyncMock(side_effect=operation)
    monkeypatch.setattr('app.routers.discovery.metadata_client.get_novel_metadata',metadata)
    monkeypatch.setattr('app.routers.discovery.metadata_client.'+('enqueue_novel_analysis' if enqueue else 'get_novel_analysis'),upstream)
    response=request(client,auth_headers,enqueue)
    expected={'blocklist':409,'signout':401,'disabled':403}[change]
    assert response.status_code==expected,response.text
    assert 'PRIVATE RESPONSE' not in response.text
    if phase=='metadata':upstream.assert_not_awaited()


@pytest.mark.parametrize('enqueue',[False,True])
def test_missing_or_failed_seed_fetch_never_dispatches(client,auth_headers,monkeypatch,enqueue):
    monkeypatch.setattr('app.routers.discovery.metadata_client.get_novel_metadata',AsyncMock(side_effect=RuntimeError('unavailable')))
    read=AsyncMock();write=AsyncMock()
    monkeypatch.setattr('app.routers.discovery.metadata_client.get_novel_analysis',read)
    monkeypatch.setattr('app.routers.discovery.metadata_client.enqueue_novel_analysis',write)
    assert request(client,auth_headers,enqueue).status_code==404
    read.assert_not_awaited();write.assert_not_awaited()


@pytest.mark.parametrize('enqueue',[False,True])
def test_cached_visible_seed_cannot_override_current_upstream_hidden_story(client,db,test_user,auth_headers,monkeypatch,enqueue):
    import httpx
    import json
    test_user.max_content_rating='general';db.commit()
    monkeypatch.setattr('app.routers.discovery.metadata_client.get_novel_metadata',AsyncMock(return_value={'title':'Cached allowed','content_rating':'general','tags':[]}))
    async def upstream(method,path,**kwargs):
        assert not db.in_transaction()
        assert method==('POST' if enqueue else 'GET')
        assert path==('/analysis/novels/901/enqueue' if enqueue else '/analysis/novels/901')
        assert json.loads(kwargs['params']['seed_visibility'])['content_rating']==['general']
        response=httpx.Response(404,json={'detail':'Story is unavailable'},request=httpx.Request(method,'https://metadata.fixture.invalid'+path))
        try:response.raise_for_status()
        except httpx.HTTPStatusError as exc:raise RuntimeError('metadata request denied') from exc
    remote=AsyncMock(side_effect=upstream)
    monkeypatch.setattr('app.routers.discovery.metadata_client._request',remote)
    response=request(client,auth_headers,enqueue)
    assert response.status_code==404,response.text
    remote.assert_awaited_once()
