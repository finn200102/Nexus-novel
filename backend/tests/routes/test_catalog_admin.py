from unittest.mock import AsyncMock

DEFINITION = {"id":7,"name":"Fixture job","site":"fanfiction","query":{},"enabled":True}
CAPABILITY = {"site":"fanfiction","name":"Fixture source","adapter_version":1,"modes":["newest"],"filters":[],"remote_filters":[],"local_filters":[]}
PREVIEW = {"query":{},"source_url":"https://fixture.invalid/list","capabilities":CAPABILITY,"estimated_pages":1,"preview":[],"matched_count":0,"warnings":[]}


def test_schedule_removal_is_forwarded_as_explicit_null(client, test_user, db, auth_headers, monkeypatch):
    test_user.is_admin = True
    db.commit()
    request = AsyncMock(return_value=DEFINITION)
    monkeypatch.setattr("app.routers.catalog_scrape._request", request)
    response = client.patch("/catalog-scrapes/7", headers=auth_headers, json={"schedule_interval_minutes": None})
    assert response.status_code == 200
    request.assert_awaited_once_with("PATCH", "/catalog-scrapes/7", json={"schedule_interval_minutes": None})


def test_readers_cannot_edit_catalog_jobs(client, auth_headers):
    response = client.patch("/catalog-scrapes/7", headers=auth_headers, json={"name": "Changed"})
    assert response.status_code == 403


def test_full_calendar_schedule_and_explicit_clear_are_preserved(client,test_user,db,auth_headers,monkeypatch):
    test_user.is_admin=True;db.commit()
    upstream=AsyncMock(return_value=DEFINITION);monkeypatch.setattr('app.routers.catalog_scrape._request',upstream)
    schedule={'kind':'weekly','days_of_week':[1,3],'hour':9,'minute':15,'timezone':'Europe/Berlin'}
    response=client.patch('/catalog-scrapes/7',headers=auth_headers,json={'schedule':schedule})
    assert response.status_code==200,response.text
    upstream.assert_awaited_once_with('PATCH','/catalog-scrapes/7',json={'schedule':schedule})
    response=client.patch('/catalog-scrapes/7',headers=auth_headers,json={'schedule':None})
    assert response.status_code==200 and upstream.await_args.kwargs['json']=={'schedule':None}


def test_plugin_review_identity_and_trusted_actor_forwarded(client,test_user,db,auth_headers,monkeypatch):
    test_user.is_admin=True;db.commit()
    upstream=AsyncMock(return_value={'definition':DEFINITION,'job':None});monkeypatch.setattr('app.routers.catalog_scrape._request',upstream)
    body={'site':'plugin-example','name':'Reviewed plugin job','query':{'mode':'newest','source_options':{'plugin_id':'example','plugin_digest':'a'*64,'plugin_version':'1.1.0','operation':'listings'}},'review_token':'reviewed','operation_id':'creation-1','schedule':{'kind':'interval','interval_minutes':60},'enabled':False}
    assert client.post('/catalog-scrapes',headers=auth_headers,json={**body,'created_by':'spoofed'}).status_code==422
    upstream.assert_not_awaited()
    result=client.post('/catalog-scrapes',headers=auth_headers,json=body)
    assert result.status_code==200 and result.headers['cache-control']=='private, no-store'
    assert upstream.await_args.kwargs['json']=={**body,'created_by':test_user.storage_id}


def test_existing_missing_templates_and_candidate_paths_are_available(client,test_user,db,auth_headers,monkeypatch):
    test_user.is_admin=True;db.commit();upstream=AsyncMock(return_value=[]);monkeypatch.setattr('app.routers.catalog_scrape._request',upstream)
    assert client.get('/catalog-scrapes/templates?site=fanfiction',headers=auth_headers).status_code==200
    upstream.assert_awaited_with('GET','/catalog-scrapes/templates',params={'site':'fanfiction'})
    upstream.return_value={'source_url':'https://fixture.invalid/story','candidate_status':'ignored'}
    assert client.patch('/catalog-scrapes/jobs/job-1/candidates/4',headers=auth_headers,json={'candidate_status':'ignored'}).status_code==200
    upstream.assert_awaited_with('PATCH','/catalog-scrapes/jobs/job-1/candidates/4',json={'candidate_status':'ignored'})
    assert client.patch('/catalog-scrapes/jobs/job-1/candidates/4',headers=auth_headers,json={'candidate_status':'imported'}).status_code==422


def test_rebind_forwards_exact_review_and_operation(client,test_user,db,auth_headers,monkeypatch):
    test_user.is_admin=True;db.commit();upstream=AsyncMock(return_value=DEFINITION);monkeypatch.setattr('app.routers.catalog_scrape._request',upstream)
    body={'query':{'mode':'newest'},'review_token':'fresh-review','expected_revision':'b'*64,'operation_id':'rebind-1'}
    assert client.post('/catalog-scrapes/7/rebind',headers=auth_headers,json=body).status_code==200
    upstream.assert_awaited_with('POST','/catalog-scrapes/7/rebind',json=body)
    control={'expected_revision':'b'*64,'operation_id':'pause-1'}
    assert client.post('/catalog-scrapes/7/pause',headers=auth_headers,json=control).status_code==200
    upstream.assert_awaited_with('POST','/catalog-scrapes/7/pause',json=control)


def test_demotion_during_upstream_hides_all_administrator_data(client,test_user,db,auth_headers,monkeypatch):
    test_user.is_admin=True;db.commit()
    async def demote(*args,**kwargs):
        test_user.is_admin=False;db.commit();return {'secret_internal_catalog':'do-not-show'}
    monkeypatch.setattr('app.routers.catalog_scrape._request',demote)
    result=client.get('/catalog-scrapes',headers=auth_headers)
    assert result.status_code==403 and 'secret_internal_catalog' not in result.text


def test_revocation_during_upstream_error_supersedes_error_body(client,test_user,db,auth_headers,monkeypatch):
    from datetime import datetime
    from fastapi import HTTPException
    from app.models.account import UserSession
    test_user.is_admin=True;db.commit()
    async def revoke(*args,**kwargs):
        db.query(UserSession).filter_by(user_id=test_user.id).update({'revoked_at':datetime.now()});db.commit()
        raise HTTPException(409,detail='private original control state')
    monkeypatch.setattr('app.routers.catalog_scrape._request',revoke)
    result=client.get('/catalog-scrapes',headers=auth_headers)
    assert result.status_code==403 and 'private original' not in result.text


def test_pooled_admin_transport_has_bounded_preview_and_redacted_errors(client,test_user,db,auth_headers,monkeypatch):
    import httpx
    test_user.is_admin=True;db.commit()
    upstream=AsyncMock(return_value=httpx.Response(200,json=PREVIEW))
    monkeypatch.setattr('app.routers.catalog_scrape.metadata_client._request',upstream)
    result=client.post('/catalog-scrapes/preview',headers=auth_headers,json={'site':'fanfiction','query':{}})
    assert result.status_code==200
    assert upstream.await_args.kwargs['admin'] is True
    assert upstream.await_args.kwargs['timeout'].read==15.0
    async def rejected(*args,**kwargs):
        response=httpx.Response(422,json={'detail':'Configured secret sk-private and internal http://service:9000'},request=httpx.Request('POST','http://metadata.invalid/preview'))
        try:raise httpx.HTTPStatusError('private secret',request=response.request,response=response)
        except httpx.HTTPStatusError as cause:raise RuntimeError('unavailable') from cause
    monkeypatch.setattr('app.routers.catalog_scrape.metadata_client._request',rejected)
    result=client.post('/catalog-scrapes/preview',headers=auth_headers,json={'query':{}})
    assert result.status_code==422 and result.json()['detail']['code']=='catalog_settings_rejected'
    assert 'sk-private' not in result.text and 'service:9000' not in result.text


def test_wire_contracts_keep_optional_unknown_source_metadata_without_filling_defaults(client,test_user,db,auth_headers,monkeypatch):
    test_user.is_admin=True;db.commit()
    payload={**DEFINITION,'definition_revision':'a'*64,'plugin_state':'ready','query':{'source_options':{'plugin_digest':'a'*64},'future_criterion':{'nested':True}},'future_source_report':{'safe':1},'schedule':None}
    upstream=AsyncMock(return_value=payload);monkeypatch.setattr('app.routers.catalog_scrape._request',upstream)
    result=client.get('/catalog-scrapes/7',headers=auth_headers)
    assert result.status_code==200 and result.json()==payload
    assert 'plugin_reason' not in result.json()
    schema=client.get('/openapi.json').json()
    for path,method in [('/catalog-scrapes/capabilities','get'),('/catalog-scrapes/preview','post'),('/catalog-scrapes','post'),('/catalog-scrapes/{definition_id}/rebind','post')]:
        assert '$ref' in schema['paths'][path][method]['responses']['200']['content']['application/json']['schema']


def test_plugin_run_delete_controls_forward_cas_and_legacy_bodyless_stays_supported(client,test_user,db,auth_headers,monkeypatch):
    test_user.is_admin=True;db.commit();upstream=AsyncMock();monkeypatch.setattr('app.routers.catalog_scrape._request',upstream)
    job={'id':'job-1','job_type':'catalog','site':'plugin-example','status':'queued','progress':0,'results':{},'attempt_count':0,'retryable':False}
    upstream.return_value=job
    body={'expected_revision':'a'*64,'operation_id':'run-1'}
    assert client.post('/catalog-scrapes/7/run',headers=auth_headers,json=body).status_code==200
    upstream.assert_awaited_with('POST','/catalog-scrapes/7/run',json=body)
    assert client.post('/catalog-scrapes/7/run',headers=auth_headers).status_code==200
    upstream.assert_awaited_with('POST','/catalog-scrapes/7/run')
    upstream.return_value={'id':7,'deleted':True}
    assert client.request('DELETE','/catalog-scrapes/7',headers=auth_headers,json=body).status_code==200
    upstream.assert_awaited_with('DELETE','/catalog-scrapes/7',json=body)


def test_plugin_update_keeps_exact_reviewed_cas_and_omits_untouched_calendar(client,test_user,db,auth_headers,monkeypatch):
    test_user.is_admin=True;db.commit()
    upstream=AsyncMock(return_value={**DEFINITION,'checkpoint':{'next_page':5},'schedule':{'kind':'weekly'}})
    monkeypatch.setattr('app.routers.catalog_scrape._request',upstream)
    body={'name':'Renamed package job','query':{'mode':'newest'},'expected_revision':'a'*64,'review_token':'fresh-review','operation_id':'stable-edit-1'}
    result=client.patch('/catalog-scrapes/7',headers=auth_headers,json=body)
    assert result.status_code==200 and result.json()['checkpoint']=={'next_page':5}
    upstream.assert_awaited_once_with('PATCH','/catalog-scrapes/7',json=body)
    assert 'schedule' not in upstream.await_args.kwargs['json']
    assert 'schedule_interval_minutes' not in upstream.await_args.kwargs['json']


def test_active_job_update_conflict_has_static_actionable_message_without_upstream_secrets(client,test_user,db,auth_headers,monkeypatch):
    import httpx
    test_user.is_admin=True;db.commit()
    async def rejected(*args,**kwargs):
        response=httpx.Response(409,json={'detail':{'code':'run_active','message':'private source password'}},request=httpx.Request('PATCH','http://metadata.invalid/catalog-scrapes/7'))
        try:raise httpx.HTTPStatusError('private',request=response.request,response=response)
        except httpx.HTTPStatusError as cause:raise RuntimeError('private') from cause
    monkeypatch.setattr('app.routers.catalog_scrape.metadata_client._request',rejected)
    result=client.patch('/catalog-scrapes/7',headers=auth_headers,json={'name':'Rename'})
    assert result.status_code==409
    assert result.json()['detail']['code']=='run_active'
    assert 'Cancel active catalog runs' in result.json()['detail']['message']
    assert 'private source password' not in result.text


def test_active_work_page_is_bounded_authorized_and_preserves_older_child_identity(client,test_user,db,auth_headers,monkeypatch):
    test_user.is_admin=True;db.commit()
    child={'id':'older-parent-import','job_type':'novel_metadata','site':'webserial','status':'queued','progress':0,'results':{},'attempt_count':0,'retryable':True,'params':{'parent_job_id':'old-run'}}
    page={'items':[child],'total':51,'offset':50,'limit':50}
    upstream=AsyncMock(return_value=page);monkeypatch.setattr('app.routers.catalog_scrape._request',upstream)
    result=client.get('/catalog-scrapes/7/active-jobs?offset=50&limit=50',headers=auth_headers)
    assert result.status_code==200 and result.json()==page
    upstream.assert_awaited_once_with('GET','/catalog-scrapes/7/active-jobs',params={'offset':50,'limit':50})
    assert client.get('/catalog-scrapes/7/active-jobs?limit=101',headers=auth_headers).status_code==422
    assert client.get('/catalog-scrapes/7/active-jobs?offset=-1',headers=auth_headers).status_code==422
    test_user.is_admin=False;db.commit()
    assert client.get('/catalog-scrapes/7/active-jobs',headers=auth_headers).status_code==403
    assert upstream.await_count==1


def test_builtin_review_state_and_durable_controls_forward_without_losing_sparse_wire_values(client,test_user,db,auth_headers,monkeypatch):
    test_user.is_admin=True;db.commit()
    legacy={**DEFINITION,'definition_revision':'a'*64,'control_state':'review_required','checkpoint':{'next_page':5}}
    upstream=AsyncMock(return_value=legacy);monkeypatch.setattr('app.routers.catalog_scrape._request',upstream)
    response=client.get('/catalog-scrapes/7',headers=auth_headers)
    assert response.status_code==200 and response.json()==legacy
    assert 'control_reason' not in response.json()
    body={'name':'Reviewed builtin job','expected_revision':'a'*64,'operation_id':'same-builtin-update','query':{'mode':'newest'},'review_token':'reviewed-current-adapter'}
    assert client.patch('/catalog-scrapes/7',headers=auth_headers,json=body).status_code==200
    upstream.assert_awaited_with('PATCH','/catalog-scrapes/7',json=body)
    control={'expected_revision':'a'*64,'operation_id':'same-builtin-resume'}
    assert client.post('/catalog-scrapes/7/resume',headers=auth_headers,json=control).status_code==200
    upstream.assert_awaited_with('POST','/catalog-scrapes/7/resume',json=control)
    upstream.return_value={'definition':legacy,'job':None}
    assert client.post('/catalog-scrapes',headers=auth_headers,json={'name':'Saved paused builtin','site':'fanfiction','query':{'mode':'newest'},'enabled':False,'review_token':'reviewed-current-adapter','operation_id':'create-builtin'}).json()['job'] is None
