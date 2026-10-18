"""Crash/retry qualification; every transport is a local recording fake."""
from datetime import datetime,timedelta
import pytest
from app.models.notification_delivery import NotificationDelivery
from app.models.notification import NotificationChannel,PushSubscription
from app.models.update_event import NovelUpdateEvent
from app.services import notification_delivery as delivery
from tests.services.test_notification_delivery import db,sent,make_user,make_novel,add_channel,add_push,event


def setup(db,*,push=False):
    user=make_user(db);novel=make_novel(db,user)
    target=add_push(db,user) if push else add_channel(db,user)
    update=event(db,user,novel)
    return user,novel,target,update


def advance(monkeypatch,seconds=90):
    now=delivery._now()+timedelta(seconds=seconds)
    monkeypatch.setattr(delivery,'_now',lambda:now)


def test_snapshot_durable_before_any_transport_and_has_no_destination_secrets(db,sent):
    user,novel,target,update=setup(db)
    assert delivery.snapshot_due_notifications(db)==(1,1)
    row=db.query(NotificationDelivery).one()
    assert row.status=='queued' and row.event_ids==[update.id]
    assert row.account_key==user.storage_id and len(row.destination_fingerprint)==64
    assert 'topic-secret' not in str(row.payload) and 'ntfy://' not in str(row.payload)
    assert sent.apprise==[] and db.get(NovelUpdateEvent,update.id).notified_at is not None


def test_failed_transport_retries_durably_with_same_tag_and_bounded_backoff(db,sent,monkeypatch):
    setup(db);sent.apprise_result=False
    report=delivery.deliver_due_notifications(db)
    row=db.query(NotificationDelivery).one()
    assert row.status=='retry_wait' and row.attempt_count==1 and report.channels_failed==1
    assert row.next_attempt_at>delivery._now()
    delivery.deliver_due_notifications(db)
    assert len(sent.apprise)==1
    advance(monkeypatch);sent.apprise_result=True
    report=delivery.deliver_due_notifications(db)
    db.refresh(row)
    assert row.status=='succeeded' and row.attempt_count==2 and report.channels_sent==1
    assert sent.apprise[0]==sent.apprise[1]
    assert db.query(NotificationDelivery).count()==1


def test_crash_before_send_recovers_expired_lease_old_worker_cannot_send(db,sent,monkeypatch):
    setup(db);delivery.snapshot_due_notifications(db)
    old=delivery.claim_delivery(db)
    assert old is not None and delivery.claim_delivery(db) is None
    advance(monkeypatch)
    new=delivery.claim_delivery(db)
    assert new[0]==old[0] and new[1]!=old[1]
    delivery.process_delivery(db,*old)
    assert sent.apprise==[]
    delivery.process_delivery(db,*new)
    assert len(sent.apprise)==1 and db.query(NotificationDelivery).one().status=='succeeded'


def test_crash_after_transport_before_ack_retries_same_payload_instead_of_losing_it(db,sent,monkeypatch):
    setup(db,push=True);delivery.snapshot_due_notifications(db);claim=delivery.claim_delivery(db)
    original=db.commit
    def crash():raise SystemExit('simulated hard crash before durable success')
    monkeypatch.setattr(db,'commit',crash)
    with pytest.raises(SystemExit):delivery.process_delivery(db,*claim)
    db.rollback();monkeypatch.setattr(db,'commit',original)
    assert len(sent.push)==1 and db.query(NotificationDelivery).one().status=='processing'
    advance(monkeypatch)
    delivery.deliver_due_notifications(db)
    assert len(sent.push)==2 and sent.push[0][1]==sent.push[1][1]
    assert db.query(NotificationDelivery).one().status=='succeeded'


@pytest.mark.parametrize('change',['disabled_account','account_identity','deleted_channel','changed_channel','disabled_channel'])
def test_authoritative_destination_and_account_fences_prevent_stale_dispatch(db,sent,change):
    user,novel,target,update=setup(db);delivery.snapshot_due_notifications(db)
    if change=='disabled_account':user.is_disabled=True
    elif change=='account_identity':user.storage_id='another-account-immutable-identity'
    elif change=='deleted_channel':db.delete(target)
    elif change=='changed_channel':target.url_encrypted='changed-opaque-secret'
    else:target.enabled=False
    db.commit();delivery.deliver_due_notifications(db)
    assert sent.apprise==[] and db.query(NotificationDelivery).one().status=='cancelled'


def test_disabled_then_reenabled_destination_never_revives_old_attempts(db,sent):
    user,novel,target,update=setup(db);delivery.snapshot_due_notifications(db)
    delivery.cancel_destination_deliveries(db,user.id,'channel',target.id);target.enabled=False;db.commit()
    target.enabled=True;db.commit();delivery.deliver_due_notifications(db)
    assert sent.apprise==[] and db.query(NotificationDelivery).one().status=='cancelled'


def test_new_destinations_and_old_event_backlog_are_not_attached_on_retry(db,sent):
    user,novel,target,update=setup(db);delivery.snapshot_due_notifications(db)
    add_push(db,user);delivery.deliver_due_notifications(db)
    assert len(sent.apprise)==1 and sent.push==[]
    older=event(db,user,novel);older.created_at=datetime(2000,1,1);db.commit()
    delivery.deliver_due_notifications(db)
    assert len(sent.apprise)==1 and sent.push==[]


def test_snapshot_rollback_preserves_event_for_next_worker(db,sent,monkeypatch):
    user,novel,target,update=setup(db);original=delivery.build_messages
    calls=0
    def fail_second(*args,**kwargs):
        nonlocal calls
        calls+=1
        if calls==2:raise RuntimeError('local snapshot interrupted')
        return original(*args,**kwargs)
    monkeypatch.setattr(delivery,'build_messages',fail_second)
    with pytest.raises(RuntimeError):delivery.snapshot_due_notifications(db)
    db.rollback();db.refresh(update)
    assert update.notified_at is None and db.query(NotificationDelivery).count()==0
    monkeypatch.setattr(delivery,'build_messages',original)
    delivery.deliver_due_notifications(db)
    assert len(sent.apprise)==1


def test_legacy_claimed_events_stay_closed_without_inventing_delivery_history(db,sent):
    user,novel,target,update=setup(db);update.notified_at=datetime(2020,1,1);db.commit()
    assert delivery.deliver_due_notifications(db).events==0
    assert db.query(NotificationDelivery).count()==0 and sent.apprise==[]


def test_retry_exhaustion_pauses_without_busy_loop_or_false_success(db,sent,monkeypatch):
    setup(db);sent.apprise_result=False
    for attempt in range(delivery.MAX_ATTEMPTS):
        delivery.deliver_due_notifications(db);advance(monkeypatch,4000)
    row=db.query(NotificationDelivery).one()
    assert row.status=='paused' and row.attempt_count==delivery.MAX_ATTEMPTS and row.finished_at is None
    assert delivery.claim_delivery(db) is None and len(sent.apprise)==delivery.MAX_ATTEMPTS


def test_catalog_match_is_deliverable_without_creating_a_library_copy(db,sent,monkeypatch):
    monkeypatch.setattr(delivery,"catalog_event_is_deliverable",lambda *args:True)
    user=make_user(db);add_push(db,user)
    db.add(NovelUpdateEvent(user_id=user.id,novel_id=None,event_type='catalog_match',notification_visible=True,
        details={'metadata_id':456,'title':'Found story','saved_search_id':12,'search_name':'My favorites','work_key':'archive:123'},message='New match for My favorites'))
    db.commit();delivery.deliver_due_notifications(db)
    assert len(sent.push)==1
    assert sent.push[0][1]['title']=='Found story' and sent.push[0][1]['url']=='/story/456'
    assert db.query(NotificationDelivery).one().status=='succeeded'


def test_catalog_visibility_rechecked_before_send_and_exact_message_event_ids(db,sent,monkeypatch):
    user,novel,target,update=setup(db,push=True)
    match=NovelUpdateEvent(user_id=user.id,novel_id=None,event_type='catalog_match',notification_visible=True,
        details={'metadata_id':456,'title':'BLOCKED MATCH'},message='Old allowed match')
    db.add(match);db.commit()
    delivery.snapshot_due_notifications(db)
    rows=db.query(NotificationDelivery).order_by(NotificationDelivery.id).all()
    assert len(rows)==2 and sorted(row.event_ids for row in rows)==sorted([[update.id],[match.id]])
    monkeypatch.setattr(delivery,'catalog_event_is_deliverable',lambda *args:False)
    delivery.deliver_due_notifications(db)
    assert len(sent.push)==1 and sent.push[0][1]['title']==novel.title
    assert sorted(row.status for row in db.query(NotificationDelivery))==['cancelled','succeeded']


def test_unverified_catalog_event_cannot_bypass_real_watch_visibility_gate(db,sent):
    user=make_user(db);add_push(db,user)
    db.add(NovelUpdateEvent(user_id=user.id,novel_id=None,event_type='catalog_match',notification_visible=True,
        details={'metadata_id':456,'title':'Unverified private match'},message='Unverified'))
    db.commit();delivery.deliver_due_notifications(db)
    assert sent.push==[] and db.query(NotificationDelivery).one().status=='cancelled'


def test_account_purge_or_id_reuse_cannot_dispatch_old_queued_content(db,sent):
    from sqlalchemy import delete
    from app.models.user import User
    user,novel,target,update=setup(db)
    uid=user.id;delivery.snapshot_due_notifications(db);claim=delivery.claim_delivery(db)
    # SQLite FK-off mirrors the explicit-purge portability defense: even an
    # orphan left by a partial old restore cannot send another account's data.
    db.execute(delete(User).where(User.id==uid));db.commit()
    delivery.process_delivery(db,*claim)
    assert sent.apprise==[] and db.query(NotificationDelivery).one().status=='cancelled'
