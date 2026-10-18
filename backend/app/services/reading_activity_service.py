"""Optional personal measurements/goals; core reading history remains independent."""
from datetime import UTC,date,datetime,timedelta
import hashlib
import json
from fastapi import HTTPException
from app.models import User,ReaderPreference,ReaderPreferenceOperation

ACTIVITY_SCOPE='reading_activity'


def utc_today():return datetime.now(UTC).date()


def validate_year(year,today=None):
    if not 1900<=year<=(today or utc_today()).year+1:raise HTTPException(422,'Choose a year from 1900 through next year')
    return year


def preference(db,user_id,scope):
    row=db.query(ReaderPreference).filter_by(user_id=user_id,scope=scope).populate_existing().first()
    defaults={'tracking_enabled':True} if scope==ACTIVITY_SCOPE else {'target_readings':None}
    return {'revision':row.revision if row else 0,'values':row.values if row else defaults}


def tracking_enabled(db,user_id,*,lock=True):
    if lock:db.query(User).filter_by(id=user_id).with_for_update().first()
    return preference(db,user_id,ACTIVITY_SCOPE)['values'].get('tracking_enabled',True) is True


def write(db,user_id,scope,value):
    db.query(User).filter_by(id=user_id).with_for_update().first()
    values=value.values.model_dump()
    signature=hashlib.sha256(json.dumps(['reading_activity',scope,value.expected_revision,values],sort_keys=True).encode()).hexdigest()
    receipt=db.query(ReaderPreferenceOperation).filter_by(user_id=user_id,operation_id=value.operation_id).first()
    if receipt:
        if receipt.fingerprint!=signature:raise HTTPException(409,detail={'code':'operation_reused','message':'This change identifier was already used for another preference'})
        return receipt.response
    current=preference(db,user_id,scope)
    if current['revision']!=value.expected_revision:raise HTTPException(409,detail={'code':'preference_conflict','current':current,'message':'This preference changed on another device; review the current choice'})
    row=db.query(ReaderPreference).filter_by(user_id=user_id,scope=scope).first()
    if row is None:row=ReaderPreference(user_id=user_id,scope=scope,revision=0,values={});db.add(row)
    row.revision=(row.revision or 0)+1;row.values=values
    response={'revision':row.revision,'values':values}
    db.add(ReaderPreferenceOperation(user_id=user_id,operation_id=value.operation_id,fingerprint=signature,response=response))
    db.commit()
    return response


def review(db,user_id,year,*,today=None):
    from app.services import reading_stats_service as stats
    today=today or utc_today();validate_year(year,today)
    start,end=date(year,1,1),date(year,12,31)
    through=min(end,today) if start<=today else None
    effective=through or date(year-1,12,31)
    summary=stats.get_summary(db,user_id=user_id,range_name='year',today=effective,calendar_start=start)
    summary.update(range='calendar_year',start=start.isoformat(),end=through.isoformat() if through else None)
    months=[dict(month=month,seconds=0,words=0,chapters_finished=0,stories_finished=0,reading_runs_finished=0,rereads_finished=0) for month in range(1,13)]
    for point in summary['daily']:
        bucket=months[date.fromisoformat(point['date']).month-1]
        for key in ('seconds','words','chapters_finished'):bucket[key]+=point[key]
    events=stats._completion_events(db,user_id)
    for month in range(1,13):
        first=date(year,month,1)
        last=date(year,month+1,1) if month<12 else date(year+1,1,1)
        last-=timedelta(days=1)
        cutoff=min(last,effective)
        completion=stats._completion_summary(db,user_id=user_id,start=first,today=cutoff,events=events)
        months[month-1].update(completion['totals'])
    goal=preference(db,user_id,f'reading_goal:{year}')['values']['target_readings']
    return dict(year=year,start=start.isoformat(),end=end.isoformat(),through=through.isoformat() if through else None,
        tracking_enabled=tracking_enabled(db,user_id,lock=False),summary=summary,months=months,
        goal=dict(target_readings=goal,completed_readings=summary['totals']['reading_runs_finished']))
