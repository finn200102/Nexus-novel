from datetime import date,datetime
from uuid import uuid4

import pytest
from sqlalchemy.orm import sessionmaker
from app.models import User,Novel,Chapter,ReaderPreference,ReadingRun,ReadingRunEvent
from app.models.reading_session import ReadingSessionDaily
from app.services import reading_activity_service as activity,reading_stats_service as stats
from app.services.reading_progress_service import save_reading_progress
from app.schemas.reading_activity import ActivityWrite
from tests.routes.test_user_data import _headers


def story(db,library):
    novel=Novel(library_id=library.id,title='Measured reading',url='https://www.royalroad.com/fiction/12345/measured',novel_site='royalroad')
    db.add(novel);db.flush()
    first=Chapter(novel_id=novel.id,chapter_number=1,title='One',content='Chapter one')
    last=Chapter(novel_id=novel.id,chapter_number=2,title='Two',content='Chapter two')
    db.add_all([first,last]);db.commit();return novel,first,last


def complete(db,user,novel,ordinal,when,inferred=False):
    run=ReadingRun(user_id=user.id,novel_id=novel.id,run_key=str(uuid4()),ordinal=ordinal,status='completed',
        progress_snapshot={},completed_at=when,completed_at_inferred=inferred)
    db.add(run);db.flush()
    db.add(ReadingRunEvent(user_id=user.id,novel_id=novel.id,run_key=run.run_key,kind='completed',occurred_at=when,inferred=inferred))
    return run


def test_tracking_optout_fences_late_heartbeats_and_aggregates_but_keeps_progress_journal(client,db,test_user,test_library,auth_headers):
    novel,first,last=story(db,test_library)
    default=client.get('/stats/preferences',headers=auth_headers)
    assert default.status_code==200 and default.json()=={'revision':0,'values':{'tracking_enabled':True}}
    assert default.headers['cache-control']=='private, no-store'
    payload=dict(novel_id=novel.id,chapter_id=first.id,seconds=30,words_read_estimate=100)
    assert client.post('/stats/reading-time',headers=auth_headers,json=payload).json()['recorded_seconds']==30
    change=dict(expected_revision=0,operation_id='disable-tracking',values={'tracking_enabled':False})
    disabled=client.put('/stats/preferences',headers=auth_headers,json=change)
    assert disabled.status_code==200 and disabled.json()['revision']==1
    for _ in range(2):assert client.post('/stats/reading-time',headers=auth_headers,json=payload).json()['recorded_seconds']==0
    save_reading_progress(db,user_id=test_user.id,chapter=last,position=0,percent=10)
    save_reading_progress(db,user_id=test_user.id,chapter=last,position=0,percent=100)
    row=db.query(ReadingSessionDaily).one()
    assert (row.seconds,row.words,row.chapters_finished)==(30,100,0)
    assert db.query(ReadingRunEvent).filter_by(kind='completed').count()==1
    review=client.get(f'/stats/review/{activity.utc_today().year}',headers=auth_headers).json()
    assert review['goal']['completed_readings']==1 and review['tracking_enabled'] is False
    assert review['summary']['totals']['chapters_finished']==0
    assert client.put('/stats/preferences',headers=auth_headers,json=change).json()==disabled.json()
    changed={**change,'operation_id':'stale-enable','values':{'tracking_enabled':True}}
    conflict=client.put('/stats/preferences',headers=auth_headers,json=changed)
    assert conflict.status_code==409 and conflict.json()['detail']['code']=='preference_conflict'
    assert client.put('/stats/preferences',headers=auth_headers,json={**changed,'operation_id':'disable-tracking'}).json()['detail']['code']=='operation_reused'
    enabled=client.put('/stats/preferences',headers=auth_headers,json={**changed,'expected_revision':1})
    assert enabled.status_code==200 and client.post('/stats/reading-time',headers=auth_headers,json=payload).json()['recorded_seconds']==30


def test_stale_session_checks_committed_optout_and_zero_heartbeat_never_inserts(db,test_user,test_library):
    novel,first,last=story(db,test_library)
    stats.record_reading_time(db,user_id=test_user.id,novel_id=novel.id,seconds=0,words=100)
    assert db.query(ReadingSessionDaily).count()==0
    db.add(ReaderPreference(user_id=test_user.id,scope='reading_activity',values={'tracking_enabled':True},revision=1));db.commit()
    cached=db.query(ReaderPreference).one();assert cached.values['tracking_enabled']
    with sessionmaker(bind=db.get_bind())() as other:
        activity.write(other,test_user.id,'reading_activity',ActivityWrite(expected_revision=1,operation_id='other-device-disable',values={'tracking_enabled':False}))
    assert stats.record_reading_time(db,user_id=test_user.id,novel_id=novel.id,seconds=60,words=500)==0
    assert db.query(ReadingSessionDaily).count()==0


def test_goal_cas_bounds_clear_and_account_isolation(client,db,test_user,auth_headers):
    year=activity.utc_today().year
    route=f'/stats/goals/{year}'
    assert client.get(route,headers=auth_headers).json()=={'revision':0,'values':{'target_readings':None}}
    body=dict(expected_revision=0,operation_id='goal-first',values={'target_readings':12})
    goal=client.put(route,headers=auth_headers,json=body)
    assert goal.status_code==200 and goal.headers['cache-control']=='private, no-store'
    assert client.put(route,headers=auth_headers,json=body).json()==goal.json()
    assert client.put(route,headers=auth_headers,json={**body,'operation_id':'stale-goal'}).status_code==409
    assert client.put(route,headers=auth_headers,json={**body,'expected_revision':1,'operation_id':'clear-goal','values':{'target_readings':None}}).json()['values']['target_readings'] is None
    for number in (0,10001,True,1.5):
        assert client.put(route,headers=auth_headers,json={**body,'values':{'target_readings':number}}).status_code==422
    other=User(username='other-goal-owner',password='unused');db.add(other);db.commit()
    assert client.get(route,headers=_headers(other)).json()['revision']==0
    assert client.get(route).status_code==401
    assert client.get('/stats/review/1899',headers=auth_headers).status_code==422
    assert client.get(f'/stats/review/{year+2}',headers=auth_headers).status_code==422


def test_calendar_review_boundaries_leap_day_rereads_and_undated_exclusion(client,db,test_user,test_library,auth_headers,monkeypatch):
    novel,first,last=story(db,test_library)
    for day,seconds in [(date(2023,12,31),900),(date(2024,1,1),300),(date(2024,2,29),600),(date(2024,12,31),450),(date(2025,1,1),1200)]:
        db.add(ReadingSessionDaily(user_id=test_user.id,novel_id=novel.id,day=day,seconds=seconds,words=seconds,chapters_finished=1))
    complete(db,test_user,novel,1,datetime(2023,12,31,23,59))
    complete(db,test_user,novel,2,datetime(2024,1,1))
    complete(db,test_user,novel,3,datetime(2024,2,29,12))
    complete(db,test_user,novel,4,datetime(2024,12,31,23,59))
    complete(db,test_user,novel,5,datetime(2025,1,1))
    complete(db,test_user,novel,6,None,True)
    db.add(ReaderPreference(user_id=test_user.id,scope='reading_goal:2024',revision=1,values={'target_readings':10}));db.commit()
    monkeypatch.setattr(activity,'utc_today',lambda:date(2025,2,1))
    response=client.get('/stats/review/2024',headers=auth_headers)
    assert response.status_code==200 and response.headers['cache-control']=='private, no-store'
    review=response.json();summary=review['summary']
    assert (review['start'],review['end'],review['through'])==('2024-01-01','2024-12-31','2024-12-31')
    assert len(summary['daily'])==366 and any(row['date']=='2024-02-29' for row in summary['daily'])
    assert summary['totals']['seconds']==1350 and summary['totals']['chapters_finished']==3
    assert summary['totals']['stories_finished']==1 and summary['totals']['reading_runs_finished']==3 and summary['totals']['rereads_finished']==3
    assert review['goal']=={'target_readings':10,'completed_readings':3}
    assert len(review['months'])==12 and review['months'][1]['seconds']==600 and review['months'][11]['reading_runs_finished']==1
    assert summary['completion_history']['undated_runs']==1 and not summary['completion_history']['undated_runs_included']
    current=activity.review(db,test_user.id,2024,today=date(2024,2,29))
    assert current['through']=='2024-02-29' and len(current['summary']['daily'])==60
    assert current['goal']['completed_readings']==2 and current['months'][11]['reading_runs_finished']==0
    future=activity.review(db,test_user.id,2025,today=date(2024,2,29))
    assert future['through'] is None and future['summary']['daily']==[] and future['goal']['completed_readings']==0
    assert all(row['seconds']==0 and row['reading_runs_finished']==0 for row in future['months'])


def test_private_review_does_not_count_other_household_members(client,db,test_user,test_library,auth_headers):
    from app.models import Library
    novel,first,last=story(db,test_library)
    other=User(username='other-review-owner',password='unused');db.add(other);db.flush()
    library=Library(user_id=other.id,name='Private');db.add(library);db.flush()
    other_story=Novel(library_id=library.id,title='Other private read');db.add(other_story);db.flush()
    db.add(ReadingSessionDaily(user_id=other.id,novel_id=other_story.id,day=activity.utc_today(),seconds=1000,words=2000,chapters_finished=1))
    complete(db,other,other_story,1,datetime.combine(activity.utc_today(),datetime.min.time()));db.commit()
    response=client.get(f'/stats/review/{activity.utc_today().year}',headers=auth_headers)
    assert response.status_code==200 and response.json()['summary']['totals']['seconds']==0
    assert response.json()['goal']['completed_readings']==0 and response.json()['summary']['top_stories']==[]


def test_activity_and_goals_portable_roundtrip_preserves_existing_choices(client,db,test_user,auth_headers):
    year=activity.utc_today().year
    client.put('/stats/preferences',headers=auth_headers,json=dict(expected_revision=0,operation_id='portable-off',values={'tracking_enabled':False}))
    client.put(f'/stats/goals/{year}',headers=auth_headers,json=dict(expected_revision=0,operation_id='portable-goal',values={'target_readings':20}))
    document=client.get('/me/export',headers=auth_headers).json()
    assert document['activity_preferences']=={'tracking_enabled':False}
    assert document['reading_goals']==[{'year':year,'values':{'target_readings':20}}]
    other=User(username='portable-activity-owner',password='unused');db.add(other);db.commit()
    imported=client.post('/me/import',headers=_headers(other),json=document)
    assert imported.status_code==200 and imported.json()['summary']['activity_preferences_applied']==1
    assert client.get('/stats/preferences',headers=_headers(other)).json()['values']['tracking_enabled'] is False
    assert client.get(f'/stats/goals/{year}',headers=_headers(other)).json()['values']['target_readings']==20
    repeat=client.post('/me/import',headers=_headers(other),json=document)
    assert repeat.json()['summary']['reading_goals_applied']==0
    document['activity_preferences']['tracking_enabled']=True
    document['reading_goals'][0]['values']['target_readings']=50
    conflict=client.post('/me/import',headers=_headers(other),json=document).json()
    assert conflict['activity_preferences']=='kept_local' and conflict['reading_goals'][0]['status']=='kept_local'
    assert client.get('/stats/preferences',headers=_headers(other)).json()['values']['tracking_enabled'] is False
    assert client.get(f'/stats/goals/{year}',headers=_headers(other)).json()['values']['target_readings']==20


def test_review_prefers_known_completion_date_over_undated_duplicate_fact(db,test_user,test_library):
    novel,_,_=story(db,test_library)
    run=complete(db,test_user,novel,1,None,True)
    db.add(ReadingRunEvent(user_id=test_user.id,novel_id=novel.id,run_key=run.run_key,kind='completed',occurred_at=datetime(2024,2,29),inferred=False));db.commit()
    review=activity.review(db,test_user.id,2024,today=date(2024,12,31))
    assert review['goal']['completed_readings']==1 and review['months'][1]['reading_runs_finished']==1
    assert review['summary']['completion_history']['undated_runs']==0
