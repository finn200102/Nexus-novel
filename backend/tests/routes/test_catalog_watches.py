"""Private query lifecycle, immutable baseline and atomic cursor evidence."""
from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import AsyncMock
import pytest
from fastapi import HTTPException
from app.models.catalog_watch import CatalogWatch, CatalogWatchSeen, CatalogMatch
from app.models.saved_search import SavedSearch
from app.models.update_event import NovelUpdateEvent
from app.models.user import User
from app.services import catalog_watch_service as svc
from app.services.saved_search_service import revision


def search(db,user):
    row=SavedSearch(user_id=user.id,name='German fantasy',filters={'version':1,'scope':'catalog','q':'magic','filters':{'language':['de'],'minWordCount':'1000'}})
    db.add(row);db.commit();return row


def prepared(db,user,row):
    snap=svc.snapshot(db,user.id,row.id,revision(row))
    state=svc.save_prepared(db,user.id,row.id,snap['proof'],'lexical',{'epoch':str(uuid4()),'prepared':{'version':1,'signature':'a'*64}})
    return db.query(CatalogWatch).filter_by(search_id=row.id).one(),state


def baseline(watch,keys=(),total=None,more=False,snapshot_id=None):
    return {'snapshot_id':snapshot_id or str(uuid4()),'epoch':watch.epoch,'through_seq':10,'total':len(keys) if total is None else total,'work_keys':list(keys),'next_after_work_key':keys[-1] if keys and more else None,'has_more':more}


def activate(db,user,row,watch,data=None):
    snap=svc.snapshot(db,user.id,row.id,revision(row),need_watch=True)
    return svc.activate(db,user.id,row.id,snap['proof'],watch.prepared_revision,data or baseline(watch))


def claim(db):
    id,token=svc.claim(db)
    return svc.worker_snapshot(db,id,token),token


def events(watch,keys=(),through=20,deleted=()):
    return {'epoch':watch.epoch,'through_seq':through,'scanned_through':through,'has_more':False,'matches':[{'work_key':key,'seq':through,'novel_id':22,'novel':{'id':22,'title':'New fantasy','author':'Writer','tags':[],'genres':[]}} for key in keys],'deleted':list(deleted)}


def test_explicit_preparation_never_activates_legacy_flag(client,db,test_user,auth_headers,monkeypatch):
    row=search(db,test_user);row.notify_on_match=True;db.commit()
    remote=AsyncMock(return_value={'epoch':str(uuid4()),'prepared':{'version':1}})
    monkeypatch.setattr('app.services.catalog_query_client.request',remote)
    response=client.get(f'/catalog-watches/{row.id}',headers=auth_headers)
    assert response.status_code==200 and response.json()['status']=='off'
    assert response.headers['cache-control']=='private, no-store'
    remote.assert_not_called()
    response=client.post(f'/catalog-watches/{row.id}/prepare',headers=auth_headers,json={'expected_revision':revision(row),'mode':'lexical'})
    assert response.status_code==200,response.text
    assert response.json()['status']=='prepared'
    assert remote.await_args.args[1]['definition']['q']=='magic'
    assert db.query(NovelUpdateEvent).count()==0


def test_paged_baseline_suppresses_old_matches_and_deduplicates(db,test_user):
    row=search(db,test_user);watch,_=prepared(db,test_user,row)
    oldkeys=sorted([str(uuid4()),str(uuid4())])
    first=baseline(watch,oldkeys[:1],total=2,more=True)
    assert activate(db,test_user,row,watch,first)['status']=='initializing'
    snap,token=claim(db)
    svc.finish_worker(db,snap,token,baseline(watch,oldkeys[1:],total=2,snapshot_id=first['snapshot_id']))
    assert svc.state(db,test_user.id,row.id)['status']=='active'
    assert db.query(CatalogWatchSeen).count()==2
    snap,token=claim(db);fresh=str(uuid4())
    svc.finish_worker(db,snap,token,events(watch,[oldkeys[0],fresh]))
    assert db.query(CatalogMatch).count()==1
    assert db.query(NovelUpdateEvent).one().details['work_key']==fresh
    watch.next_check_at=None;db.commit();snap,token=claim(db)
    svc.finish_worker(db,snap,token,events(watch,[fresh],through=21))
    assert db.query(CatalogMatch).count()==1 and db.query(CatalogWatchSeen).count()==3


def test_late_worker_cannot_commit_after_pause(db,test_user):
    row=search(db,test_user);watch,_=prepared(db,test_user,row)
    state=activate(db,test_user,row,watch);snap,token=claim(db)
    svc.pause(db,test_user.id,row.id,revision(row),state['revision'])
    assert svc.finish_worker(db,snap,token,events(watch,[str(uuid4())])) is False
    assert db.query(CatalogMatch).count()==0


def test_visibility_change_fences_results_and_outbound(db,test_user):
    row=search(db,test_user);watch,_=prepared(db,test_user,row)
    activate(db,test_user,row,watch);snap,token=claim(db)
    svc.finish_worker(db,snap,token,events(watch,[str(uuid4())]))
    event=db.query(NovelUpdateEvent).one()
    assert svc.event_is_deliverable(db,test_user,event)
    test_user.blocked_tags=['blocked'];db.commit()
    assert not svc.event_is_deliverable(db,test_user,event)
    state=svc.state(db,test_user.id,row.id)
    assert state['status']=='paused' and state['prepared_revision'] is None
    assert svc.matches(db,test_user.id,row.id,0,50)['total']==0


def test_epoch_and_ahead_cursor_require_review(db,test_user):
    row=search(db,test_user);watch,_=prepared(db,test_user,row)
    activate(db,test_user,row,watch);snap,token=claim(db)
    data=events(watch);data['epoch']=str(uuid4())
    svc.finish_worker(db,snap,token,data);db.refresh(watch)
    assert watch.status=='paused' and watch.cursor==10
    assert db.query(CatalogMatch).count()==0


def test_lease_recovers_and_fences_original_worker(db,test_user):
    row=search(db,test_user);watch,_=prepared(db,test_user,row)
    activate(db,test_user,row,watch);snap,token=claim(db)
    assert svc.claim(db) is None
    newer=svc.claim(db,datetime.utcnow()+timedelta(seconds=100))
    assert newer and newer[1]!=token
    assert svc.finish_worker(db,snap,token,events(watch)) is False
    latest=svc.worker_snapshot(db,*newer)
    assert svc.finish_worker(db,latest,newer[1],events(watch))


def test_delete_then_reused_numeric_id_is_new_work(db,test_user):
    row=search(db,test_user);watch,_=prepared(db,test_user,row)
    activate(db,test_user,row,watch);key=str(uuid4());snap,token=claim(db)
    svc.finish_worker(db,snap,token,events(watch,[key]))
    watch.next_check_at=None;db.commit();snap,token=claim(db)
    svc.finish_worker(db,snap,token,events(watch,through=21,deleted=[{'seq':21,'work_key':key,'novel_id':22}]))
    assert db.query(CatalogMatch).count()==0
    assert not db.query(NovelUpdateEvent).one().notification_visible
    watch.next_check_at=None;db.commit();snap,token=claim(db);newkey=str(uuid4())
    svc.finish_worker(db,snap,token,events(watch,[newkey],through=22))
    assert db.query(CatalogMatch).one().work_key==newkey


def test_read_match_is_owned_and_idempotent(client,db,test_user,auth_headers):
    row=search(db,test_user);watch,_=prepared(db,test_user,row)
    state=activate(db,test_user,row,watch);snap,token=claim(db)
    svc.finish_worker(db,snap,token,events(watch,[str(uuid4())]))
    match=db.query(CatalogMatch).one();url=f'/catalog-watches/{row.id}/matches/{match.id}/read'
    assert client.post(url,headers=auth_headers,json={'watch_revision':state['revision']}).status_code==200
    db.refresh(match);first=match.read_at
    assert client.post(url,headers=auth_headers,json={'watch_revision':state['revision']}).status_code==200
    db.refresh(match)
    assert match.read_at==first and db.query(NovelUpdateEvent).one().read_at==first
    other=User(username='foreign',password='unused');db.add(other);db.commit()
    with pytest.raises(HTTPException) as exc:svc.matches(db,other.id,row.id,0,50)
    assert exc.value.status_code==404


def test_failed_baseline_rolls_back_receipts(db,test_user):
    row=search(db,test_user);watch,_=prepared(db,test_user,row)
    with pytest.raises(HTTPException):activate(db,test_user,row,watch,baseline(watch,[str(uuid4())],total=2))
    db.rollback();db.refresh(watch)
    assert watch.status=='prepared' and db.query(CatalogWatchSeen).count()==0


def test_prepared_response_cannot_cross_changed_permission(db,test_user):
    row=search(db,test_user);snap=svc.snapshot(db,test_user.id,row.id,revision(row))
    test_user.max_content_rating='teen';db.commit()
    with pytest.raises(HTTPException) as exc:svc.save_prepared(db,test_user.id,row.id,snap['proof'],'lexical',{'epoch':str(uuid4()),'prepared':{}})
    assert exc.value.status_code==409
    db.rollback();assert db.query(CatalogWatch).count()==0


def test_guarded_recovery_fixture_retains_private_watch_and_retry(db,test_user,monkeypatch,capsys):
    import runpy,sys
    from pathlib import Path
    import httpx
    test_user.is_admin=True;db.commit()
    row=search(db,test_user);row.name='Real catalog alerts';db.commit()
    watch,_=prepared(db,test_user,row)
    oldkey=str(uuid4());newkey=str(uuid4())
    state=activate(db,test_user,row,watch,baseline(watch,[oldkey]))
    snap,token=claim(db)
    data=events(watch,[newkey]);data['matches'][0]['novel']['id']=987654401
    svc.finish_worker(db,snap,token,data)
    match=db.query(CatalogMatch).one()
    svc.read_match(db,test_user.id,row.id,match.id,state['revision'])
    svc.pause(db,test_user.id,row.id,revision(row),state['revision'])
    monkeypatch.setenv('NEXUS_CATALOG_WATCH_ACCEPTANCE','1')
    monkeypatch.setattr('config.database.SessionLocal',lambda:db)
    def forbidden(*args,**kwargs):raise AssertionError('Recovery fixture must never contact a service')
    monkeypatch.setattr(httpx.Client,'request',forbidden);monkeypatch.setattr(httpx.AsyncClient,'request',forbidden)
    path=Path(__file__).resolve().parents[4]/'scripts/catalog-watch-acceptance-fixture.py'
    for mode in ('backend-seed','backend-verify'):
        monkeypatch.setattr(sys,'argv',[str(path),mode]);runpy.run_path(str(path),run_name='__main__')
    assert 'durable retry state verified' in capsys.readouterr().out


@pytest.mark.parametrize('key_factory',[lambda:str(uuid4()),lambda:uuid4().hex])
def test_replacing_query_removes_old_receipts_and_deleted_keys_accept_both_databases(db,test_user,key_factory):
    row=search(db,test_user);watch,_=prepared(db,test_user,row)
    activate(db,test_user,row,watch);key=key_factory();snap,token=claim(db)
    svc.finish_worker(db,snap,token,events(watch,[key]))
    watch.next_check_at=None;db.commit();snap,token=claim(db)
    svc.finish_worker(db,snap,token,events(watch,through=21,deleted=[{'work_key':key,'seq':21,'novel_id':22}]))
    assert db.query(CatalogMatch).count()==0
    assert db.query(CatalogWatchSeen).count()==1
    # Preparing the explicitly reviewed replacement starts a fresh watch;
    # stale notifications cannot survive with the replaced query's event IDs.
    deleted_event=db.query(NovelUpdateEvent).one()
    assert not deleted_event.notification_visible
    watch.next_check_at=None;db.commit();snap,token=claim(db)
    svc.finish_worker(db,snap,token,events(watch,[key_factory()],through=22))
    old_event_id=db.query(CatalogMatch).one().event_id
    watch,state=prepared(db,test_user,row)
    assert state['status']=='prepared' and state['match_count']==0
    assert db.query(NovelUpdateEvent).filter_by(id=old_event_id).count()==0
    assert db.query(CatalogWatchSeen).count()==0
    assert not svc.event_is_deliverable(db,test_user,deleted_event)


def test_idle_ranked_observation_detects_time_promotion_once_without_advancing_clock(db,test_user):
    row=search(db,test_user);watch,_=prepared(db,test_user,row)
    activate(db,test_user,row,watch,baseline(watch,[str(uuid4())]))
    key=str(uuid4())
    for attempt in range(2):
        watch.next_check_at=None;db.commit();snap,token=claim(db)
        page=events(watch,[key],through=10)
        page['matches'][0]['kind']='ranked_observation'
        assert svc.finish_worker(db,snap,token,page)
        db.refresh(watch)
        assert watch.cursor==10 and db.query(CatalogMatch).count()==1
        assert db.query(NovelUpdateEvent).count()==1 and db.query(CatalogWatchSeen).count()==2


@pytest.mark.parametrize('kind,seq,q',[('change',10,'magic'),('ranked_observation',9,'magic'),('ranked_observation',11,'magic'),('ranked_observation',10,''),('unrecognized',10,'magic')])
def test_idle_observation_does_not_weaken_actual_event_or_filter_query_fences(db,test_user,kind,seq,q):
    row=search(db,test_user);row.filters={**row.filters,'q':q};db.commit()
    watch,_=prepared(db,test_user,row);activate(db,test_user,row,watch)
    snap,token=claim(db);page=events(watch,[str(uuid4())],through=10)
    page['matches'][0].update(kind=kind,seq=seq)
    with pytest.raises(HTTPException):svc.finish_worker(db,snap,token,page)
    db.rollback()
    assert db.query(CatalogMatch).count()==db.query(NovelUpdateEvent).count()==db.query(CatalogWatchSeen).count()==0
    assert db.query(CatalogWatch).one().cursor==10
