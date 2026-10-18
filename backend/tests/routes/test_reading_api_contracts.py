from copy import deepcopy
from uuid import uuid4

from app.main import app
from app.models import Novel,ReadingRun,ReadingProgressOperation,ReaderPreference,ReaderPreferenceOperation
from app.services.reading_run_service import state
from app.services import reading_activity_service as activity


def test_openapi_declares_named_nonempty_reading_contracts_without_io(monkeypatch):
    from config.database import engine
    from app import main
    import httpx
    def forbidden(*args,**kwargs):raise AssertionError('Contract generation must not start services, access a database, or fetch data')
    monkeypatch.setattr(engine,'connect',forbidden)
    monkeypatch.setattr(main,'upgrade_database',forbidden)
    monkeypatch.setattr(main.metadata_client,'start',forbidden)
    monkeypatch.setattr(httpx.Client,'send',forbidden)
    monkeypatch.setattr(httpx.AsyncClient,'send',forbidden)
    previous=app.openapi_schema
    try:
        app.openapi_schema=None
        document=app.openapi()
    finally:app.openapi_schema=previous
    expected={
        ('/stats/reading-time','post'):'ReadingTimeResponse',
        ('/stats/summary','get'):'StatsSummaryResponse',
        ('/stats/preferences','get'):'ReadingActivityPreferenceResponse',
        ('/stats/preferences','put'):'ReadingActivityPreferenceResponse',
        ('/stats/goals/{year}','get'):'ReadingGoalResponse',
        ('/stats/goals/{year}','put'):'ReadingGoalResponse',
        ('/stats/review/{year}','get'):'CalendarYearReviewResponse',
        ('/reading/stories/{novel_id}/runs','get'):'ReadingRunStateResponse',
        ('/reading/stories/{novel_id}/runs/start','post'):'ReadingRunStateResponse',
        ('/reading/stories/{novel_id}/runs/finish','post'):'ReadingRunStateResponse',
        ('/reading/stories/{novel_id}/runs/drop','post'):'ReadingRunStateResponse',
        ('/reading/journal','get'):'ReadingJournalPageResponse',
        ('/reader/preferences','get'):'ReaderPreferenceResponse',
        ('/reader/preferences','put'):'ReaderPreferenceResponse',
        ('/reader/preferences/stories/{novel_id}','get'):'ReaderPreferenceResponse',
        ('/reader/preferences/stories/{novel_id}','put'):'ReaderPreferenceResponse',
    }
    schemas=document['components']['schemas']
    for (path,method),name in expected.items():
        response=document['paths'][path][method]['responses']['200']['content']['application/json']['schema']
        assert response=={'$ref':f'#/components/schemas/{name}'}
        assert schemas[name].get('properties') and schemas[name].get('required')
    assert 'tracking_enabled' in schemas['ActivityValuesResponse']['required']
    assert 'target_readings' in schemas['GoalValuesResponse']['required']
    assert schemas['ReadingRunProgressResponse']['additionalProperties'] is True
    assert 'percent' not in schemas['ReadingRunProgressResponse'].get('required',[])
    assert schemas['StatsSummaryResponse']['properties']['range']['enum']==['week','month','year','all']
    assert schemas['CalendarStatsSummaryResponse']['properties']['range']['const']=='calendar_year'
    assert {'type':'null'} in schemas['CalendarStatsSummaryResponse']['properties']['end']['anyOf']


def test_reader_preference_contract_preserves_sparse_null_and_future_values_and_receipts(client,db,test_user,test_library,auth_headers):
    assert client.get('/reader/preferences',headers=auth_headers).json()=={'scope':'global','revision':0,'values':{}}
    values={'typography':{'font':'literata','future_font_option':{'enabled':True}},'future_reader_control':['keep','verbatim'],'layout':None}
    db.add(ReaderPreference(user_id=test_user.id,scope='global',revision=3,values=values));db.commit()
    response=client.get('/reader/preferences',headers=auth_headers)
    assert response.status_code==200 and response.json()=={'scope':'global','revision':3,'values':values}
    novel=Novel(library_id=test_library.id,title='Sparse preferences');db.add(novel);db.commit()
    assert client.get(f'/reader/preferences/stories/{novel.id}',headers=auth_headers).json()['values']=={}
    request=dict(expected_revision=0,operation_id='typed-story-preference',values={'typography':{'fontSize':20}})
    first=client.put(f'/reader/preferences/stories/{novel.id}',headers=auth_headers,json=request)
    assert first.status_code==200 and first.json()['values']=={'typography':{'fontSize':20}}
    receipt=db.query(ReaderPreferenceOperation).filter_by(user_id=test_user.id,operation_id=request['operation_id']).one()
    body=deepcopy(receipt.response);body['values']['future_receipt_field']={'public':'retained'};body['legacy_receipt_marker']=True
    receipt.response=body;db.commit()
    replay=client.put(f'/reader/preferences/stories/{novel.id}',headers=auth_headers,json=request)
    assert replay.status_code==200 and replay.json()==body


def test_reading_run_contract_preserves_sparse_portable_snapshot_and_exact_action_receipt(client,db,test_user,test_library,auth_headers):
    novel=Novel(library_id=test_library.id,title='Portable journal contract');db.add(novel);db.flush()
    snapshot={'reading_run_key':str(uuid4()),'_portable_ordinal':1,'_portable_source_key':'source-key','future_snapshot_value':{'keep':[1,False,None]}}
    run=ReadingRun(user_id=test_user.id,novel_id=novel.id,run_key=snapshot['reading_run_key'],ordinal=7,
        progress_snapshot=snapshot,started_at_inferred=True)
    db.add(run);db.commit()
    response=client.get(f'/reading/stories/{novel.id}/runs',headers=auth_headers)
    assert response.status_code==200
    assert response.json()['items'][0]['progress']==snapshot
    assert response.json()['items'][0]['ordinal']==1
    assert response.json()['current_progress'] is None
    request=dict(expected_revision=0,operation_id='typed-run-finish')
    first=client.post(f'/reading/stories/{novel.id}/runs/finish',headers=auth_headers,json=request)
    assert first.status_code==200
    receipt=db.query(ReadingProgressOperation).filter_by(user_id=test_user.id,operation_id=request['operation_id']).one()
    body=deepcopy(receipt.response)
    body['current_progress']={'reading_run_key':run.run_key,'revision':1,'legacy_position_marker':{'retained':True}}
    body['items'][0]['progress']=snapshot
    body.pop('first_chapter_number',None)
    receipt.response=body;db.commit()
    replay=client.post(f'/reading/stories/{novel.id}/runs/finish',headers=auth_headers,json=request)
    assert replay.status_code==200 and replay.json()==body


def test_stats_response_validation_preserves_service_payload_and_future_calendar_null(client,db,test_user,auth_headers,monkeypatch):
    from app.services import reading_stats_service as stats
    expected=stats.get_summary(db,user_id=test_user.id,range_name='week')
    response=client.get('/stats/summary?range=week',headers=auth_headers)
    assert response.status_code==200 and response.json()==expected
    year=activity.utc_today().year+1
    expected=activity.review(db,test_user.id,year)
    response=client.get(f'/stats/review/{year}',headers=auth_headers)
    assert response.status_code==200 and response.json()==expected
    assert response.json()['summary']['end'] is None and response.json()['through'] is None
    # Older service/receipt output omits later completion extensions. Validation
    # must not synthesize nulls in their place or discard future public fields.
    legacy=deepcopy(stats.get_summary(db,user_id=test_user.id,range_name='week'))
    legacy.pop('completion_history');legacy['totals'].pop('reading_runs_finished');legacy['totals'].pop('rereads_finished')
    legacy['future_public_summary']={'keep':True}
    monkeypatch.setattr(stats,'get_summary',lambda *args,**kwargs:legacy)
    assert client.get('/stats/summary',headers=auth_headers).json()==legacy
