from datetime import datetime
from unittest.mock import AsyncMock
import httpx
import pytest
from app.models.account import UserSession


def admin(test_user,db):
    test_user.is_admin=True
    db.commit()


def rejected(status,detail):
    response=httpx.Response(status,json={'detail':detail},request=httpx.Request('POST','http://metadata.invalid/private?token=PRIVATE_URL_MARKER'))
    cause=httpx.HTTPStatusError('PRIVATE_EXCEPTION_MARKER',request=response.request,response=response)
    error=RuntimeError('PRIVATE_WRAPPED_MARKER')
    error.__cause__=cause
    return error


def test_schedule_endpoints_share_pooled_privileged_transport_and_private_headers(client,test_user,db,auth_headers,monkeypatch):
    admin(test_user,db)
    transport=AsyncMock(return_value=httpx.Response(200,json={'id':'schedule-1','site':'royalroad'}))
    monkeypatch.setattr('app.routers.operations.metadata_client._request',transport)
    monkeypatch.setattr('app.routers.operations._metadata_proxy',lambda *args,**kwargs:pytest.fail('Legacy sync transport must not be used'))
    for method,path,body,upstream in [
        ('GET','/operations/schedules',None,'/api/refresh-schedules/'),
        ('POST','/operations/schedules',{'site':'royalroad','interval_minutes':60,'batch_size':10,'enabled':False},'/api/refresh-schedules/'),
        ('PATCH','/operations/schedules/schedule-1',{'enabled':False},'/api/refresh-schedules/schedule-1'),
        ('POST','/operations/schedules/schedule-1/run',None,'/api/refresh-schedules/schedule-1/run'),
        ('DELETE','/operations/schedules/schedule-1',None,'/api/refresh-schedules/schedule-1'),
    ]:
        response=client.request(method,path,headers=auth_headers,**({'json':body} if body is not None else {}))
        assert response.status_code==(201 if method=='POST' and path=='/operations/schedules' else 200),response.text
        assert response.headers['cache-control']=='private, no-store'
        args,kwargs=transport.await_args
        assert args==(method,upstream) and kwargs['admin'] is True
        assert kwargs['timeout'].read==10.0
        if body is not None:assert kwargs['json']==body


@pytest.mark.parametrize('method,path,body',[
    ('GET','/operations/schedules',None),('POST','/operations/schedules',{'site':'royalroad'}),
    ('PATCH','/operations/schedules/x',{'enabled':True}),('POST','/operations/schedules/x/run',None),('DELETE','/operations/schedules/x',None),
])
def test_readers_never_reach_refresh_schedule_transport(client,auth_headers,monkeypatch,method,path,body):
    transport=AsyncMock();monkeypatch.setattr('app.routers.operations.metadata_client._request',transport)
    response=client.request(method,path,headers=auth_headers,**({'json':body} if body is not None else {}))
    assert response.status_code==403 and response.headers['cache-control']=='private, no-store'
    transport.assert_not_awaited()


@pytest.mark.parametrize('detail',[
    'AO3 refreshes require an explicit reader action; recurring refreshes are unavailable',
    'AO3 refreshes require an explicit reader action',
])
def test_exact_ao3_policy_errors_remain_actionable_without_forwarding_arbitrary_text(client,test_user,db,auth_headers,monkeypatch,detail):
    admin(test_user,db)
    monkeypatch.setattr('app.routers.operations.metadata_client._request',AsyncMock(side_effect=rejected(400,detail)))
    response=client.post('/operations/schedules',headers=auth_headers,json={'site':'archive'})
    assert response.status_code==400
    assert response.json()['detail']['code']=='user_initiated_refresh_required'
    assert 'explicit reader action' in response.json()['detail']['message']
    assert response.headers['cache-control']=='private, no-store'


def test_unknown_upstream_body_and_transport_credentials_are_redacted(client,test_user,db,auth_headers,monkeypatch):
    admin(test_user,db)
    transport=AsyncMock(side_effect=rejected(400,'PRIVATE_BODY_MARKER password=PRIVATE_CREDENTIAL_MARKER'))
    monkeypatch.setattr('app.routers.operations.metadata_client._request',transport)
    response=client.post('/operations/schedules',headers=auth_headers,json={'site':'royalroad'})
    assert response.status_code==400 and 'PRIVATE_' not in response.text
    assert response.json()['detail']['code']=='refresh_schedule_rejected'
    transport.side_effect=httpx.ConnectError('PRIVATE_TRANSPORT_MARKER https://user:password@internal.invalid')
    response=client.get('/operations/schedules',headers=auth_headers)
    assert response.status_code==503 and 'PRIVATE_' not in response.text and 'internal.invalid' not in response.text
    assert response.headers['cache-control']=='private, no-store'


def test_revoked_admin_session_during_request_hides_success_and_upstream_error(client,test_user,db,auth_headers,monkeypatch):
    admin(test_user,db)
    async def revoke(*args,**kwargs):
        db.query(UserSession).filter_by(user_id=test_user.id).update({'revoked_at':datetime.now()});db.commit()
        raise rejected(400,'PRIVATE_REVOKED_BODY')
    monkeypatch.setattr('app.routers.operations.metadata_client._request',revoke)
    response=client.get('/operations/schedules',headers=auth_headers)
    assert response.status_code==403 and 'PRIVATE_' not in response.text


def test_admin_demotion_during_schedule_response_hides_private_snapshot(client,test_user,db,auth_headers,monkeypatch):
    admin(test_user,db)
    async def demote(*args,**kwargs):
        test_user.is_admin=False;db.commit()
        return httpx.Response(200,json={'private_schedule':'DO_NOT_DISCLOSE'})
    monkeypatch.setattr('app.routers.operations.metadata_client._request',demote)
    response=client.get('/operations/schedules',headers=auth_headers)
    assert response.status_code==403 and 'DO_NOT_DISCLOSE' not in response.text
