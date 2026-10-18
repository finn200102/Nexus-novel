"""Run identity, durable completion facts, and explicit reading actions."""
from uuid import uuid4
from datetime import datetime
import hashlib
import json
from fastapi import HTTPException
from sqlalchemy import func
from app.models import Chapter, User, Novel, Library
from app.models.novel_personal import NovelPersonalData
from app.models.reading_progress import ReadingProgress, ReadingProgressOperation
from app.models.reading_history import ReadingHistory
from app.models.reading_run import ReadingRun, ReadingRunEvent
from app.services.library_organization_service import followed_categories_of
from app.services.job_lease import utcnow

PROGRESS_FIELDS=('chapter_key','furthest_chapter_key','current_identity_inferred','furthest_identity_inferred','manifest_epoch','manifest_revision','source_content_version','furthest_content_version','novel_id','chapter_number','position','percent','revision','furthest_chapter_number','furthest_percent',
    'block_id','text_offset','text_quote','quote_prefix','quote_suffix','locator_content_version','locator_variant','reading_run_key')


def progress_view(progress):
    if progress is None:return None
    result={key:getattr(progress,key,None) for key in PROGRESS_FIELDS}
    result['updated_at']=progress.updated_at.isoformat() if progress.updated_at else None
    return result


def restore_progress(run):
    """Retain revision/run counters if a deleted chapter cascaded its old row."""
    snapshot=run.progress_snapshot if run is not None else None
    if not isinstance(snapshot,dict) or 'revision' not in snapshot:return None
    values={key:snapshot.get(key) for key in PROGRESS_FIELDS if key in snapshot and key!='novel_id'}
    values.setdefault('current_identity_inferred',values.get('chapter_key') is None and values.get('chapter_number') is not None)
    values.setdefault('furthest_identity_inferred',int(values.get('furthest_chapter_key') is None and (values.get('furthest_chapter_number',0)!=0 or (values.get('furthest_percent') or 0)>0)))
    progress=ReadingProgress(user_id=run.user_id,novel_id=run.novel_id,**values)
    if snapshot.get('updated_at'):
        try:progress.updated_at=datetime.fromisoformat(snapshot['updated_at'])
        except (ValueError,TypeError):pass
    return progress


def snapshot_progress(run,progress):
    metadata={key:value for key,value in (run.progress_snapshot or {}).items() if key.startswith('_portable_')}
    return {**metadata,**progress_view(progress)}


def owned_story(db,user_id,novel_id):
    row=db.query(Novel).join(Library).filter(Novel.id==novel_id,Library.user_id==user_id).first()
    if row is None:raise HTTPException(404,'Story not found')
    return row


def followed_chapters(db,user_id,novel_id):
    personal=db.query(NovelPersonalData).filter_by(user_id=user_id,novel_id=novel_id).first()
    return db.query(Chapter).filter(Chapter.novel_id==novel_id,Chapter.category.in_(followed_categories_of(personal)))


def current_run(db,user_id,novel_id,progress=None):
    if progress is not None and progress.reading_run_key:
        return db.query(ReadingRun).filter_by(user_id=user_id,novel_id=novel_id,run_key=progress.reading_run_key).first()
    return db.query(ReadingRun).filter_by(user_id=user_id,novel_id=novel_id).filter(ReadingRun.archived_at.is_(None)).order_by(ReadingRun.ordinal.desc()).first()


def next_ordinal(db,user_id,novel_id):
    return (db.query(func.max(ReadingRun.ordinal)).filter_by(user_id=user_id,novel_id=novel_id).scalar() or 0)+1


def display_ordinal(run):
    from sqlalchemy.orm.exc import DetachedInstanceError
    try:group=getattr(run,'continuity',None)
    except DetachedInstanceError:group=None
    if group is not None and group.user_id==run.user_id:return group.logical_ordinal
    value=(run.progress_snapshot or {}).get('_portable_ordinal')
    return value if isinstance(value,int) and not isinstance(value,bool) and value>0 else run.ordinal


def event(db,run,kind,*,inferred=False,reason=None,when=None):
    db.add(ReadingRunEvent(user_id=run.user_id,novel_id=run.novel_id,run_key=run.run_key,kind=kind,
        occurred_at=None if inferred else when or utcnow(),inferred=inferred,reason=reason))


def ensure_run(db,user_id,novel_id,progress=None,*,legacy=False):
    run=current_run(db,user_id,novel_id,progress)
    if run is None:
        run=ReadingRun(user_id=user_id,novel_id=novel_id,run_key=str(uuid4()),ordinal=next_ordinal(db,user_id,novel_id),status='active',requires_run_key=False,
            started_at=None if legacy else utcnow(),started_at_inferred=legacy,progress_snapshot={})
        db.add(run);db.flush();
        from app.services.reading_continuity_service import new_reading
        new_reading(db,run)
        event(db,run,'started',inferred=legacy,when=run.started_at)
        # Unscoped legacy points belong to this first local run, never to a
        # historical archive imported afterward.
        db.query(ReadingHistory).filter_by(user_id=user_id,novel_id=novel_id,reading_run_key=None).update(
            {'reading_run_key':run.run_key},synchronize_session=False)
    if progress is not None:
        progress.reading_run_key=run.run_key
        if legacy and not run.completed_at and not run.completed_at_inferred:
            last=followed_chapters(db,user_id,novel_id).with_entities(func.max(Chapter.chapter_number)).scalar()
            if last is not None and progress.chapter_number==last and (progress.percent or 0)>=95:mark_complete(db,run,inferred=True)
    return run


def check_run_key(run,provided,progress):
    if (run is None and provided is not None) or (run is not None and ((provided is not None and str(provided)!=run.run_key) or (run.requires_run_key and provided is None))):
        raise HTTPException(409,detail={'code':'reading_run_changed','current':progress_view(progress),
            'message':'This story has a different reading run. Keep the offline position for review and reload the current run.'})


def mark_complete(db,run,*,inferred=False):
    from app.services.reading_continuity_service import complete
    complete(db,run,inferred=inferred)


def update_run(db,run,progress):
    run.progress_snapshot=snapshot_progress(run,progress)
    last=followed_chapters(db,run.user_id,run.novel_id).with_entities(func.max(Chapter.chapter_number)).scalar()
    if last is not None and progress.chapter_number==last and progress.percent>=95:mark_complete(db,run)


def run_view(db,run,current=None):
    progress=progress_view(current) if current is not None and current.reading_run_key==run.run_key else run.progress_snapshot
    from app.services.reading_order import next_unread_for_run
    point=current if current is not None and current.reading_run_key==run.run_key else restore_progress(run)
    next_chapter=next_unread_for_run(db,run.user_id,run.novel_id,point,run)
    return dict(reading_run_key=run.run_key,ordinal=display_ordinal(run),status=run.status,
        started_at=run.started_at,started_at_inferred=run.started_at_inferred,completed_at=run.completed_at,
        completed_at_inferred=run.completed_at_inferred,abandoned_at=run.abandoned_at,abandon_reason=run.abandon_reason,
        archived_at=run.archived_at,progress=progress,next_unread_chapter_id=next_chapter.id if next_chapter else None,
        next_unread_chapter_number=next_chapter.chapter_number if next_chapter else None)


def state(db,user_id,novel_id,offset=0,limit=50):
    owned_story(db,user_id,novel_id)
    progress=db.query(ReadingProgress).filter_by(user_id=user_id,novel_id=novel_id).first()
    run=current_run(db,user_id,novel_id,progress)
    if progress is None:progress=restore_progress(run)
    query=db.query(ReadingRun).filter_by(user_id=user_id,novel_id=novel_id)
    first=followed_chapters(db,user_id,novel_id).with_entities(Chapter.id,Chapter.chapter_key,Chapter.chapter_number).order_by(Chapter.chapter_number).first()
    return dict(novel_id=novel_id,current_run_key=run.run_key if run else None,revision=(progress.revision or 0) if progress else 0,
        current_progress=progress_view(progress),first_chapter_number=first.chapter_number if first else None,
        total=query.count(),offset=offset,limit=limit,
        items=[run_view(db,row,progress) for row in query.order_by(ReadingRun.ordinal.desc()).offset(offset).limit(limit)])


def action(db,user_id,novel_id,value,kind):
    owned_story(db,user_id,novel_id)
    db.query(User).filter_by(id=user_id).with_for_update().first()
    payload=value.model_dump(mode='json')
    signature=hashlib.sha256(json.dumps(['reading_run',kind,novel_id,payload],sort_keys=True).encode()).hexdigest()
    receipt=db.query(ReadingProgressOperation).filter_by(user_id=user_id,operation_id=value.operation_id).first()
    if receipt:
        if receipt.novel_id!=novel_id or receipt.fingerprint!=signature:raise HTTPException(409,detail={'code':'operation_reused','message':'This action identifier was used for another change'})
        return receipt.response
    progress=db.query(ReadingProgress).filter_by(user_id=user_id,novel_id=novel_id).first()
    run=current_run(db,user_id,novel_id,progress)
    recovering=progress is None
    if recovering:progress=restore_progress(run)
    check_run_key(run,value.reading_run_key,progress)
    if value.expected_revision!=((progress.revision or 0) if progress else 0):
        raise HTTPException(409,detail={'code':'progress_conflict','current':progress_view(progress),'message':'Reading progress changed; review the current position before this action'})
    first=followed_chapters(db,user_id,novel_id).with_entities(Chapter.id,Chapter.chapter_key,Chapter.chapter_number).order_by(Chapter.chapter_number).first() if kind=='start' else None
    if kind=='start' and first is None:raise HTTPException(409,'This story has no followed chapters to start')
    fresh_start=kind=='start' and run is None and (progress is None or progress.chapter_number is None)
    if progress is None:
        progress=ReadingProgress(user_id=user_id,novel_id=novel_id,position=0,percent=0,revision=0,
            furthest_chapter_number=0,furthest_percent=0,text_offset=0)
        db.add(progress);db.flush()
    if recovering and progress is not None:db.add(progress)
    run=ensure_run(db,user_id,novel_id,progress,legacy=bool(progress.chapter_number))
    now=utcnow()
    if kind=='start':
        if fresh_start:
            run.requires_run_key=True
        else:
            run.progress_snapshot=snapshot_progress(run,progress);run.archived_at=now
            previous_run=run
            run=ReadingRun(user_id=user_id,novel_id=novel_id,run_key=str(uuid4()),ordinal=next_ordinal(db,user_id,novel_id),status='active',
                requires_run_key=True,started_at=now,started_at_inferred=False,completed_at_inferred=False,progress_snapshot={})
            db.add(run);db.flush()
            from app.services.reading_continuity_service import new_reading
            new_reading(db,run,previous_run)
            event(db,run,'started',when=now)
        progress.chapter_id=first.id;progress.chapter_key=first.chapter_key;progress.current_identity_inferred=False;progress.chapter_number=first.chapter_number;progress.position=0;progress.percent=0
        from app.services.chapter_identity_service import manifest_state,state_fields
        header=state_fields(manifest_state(db,novel_id));progress.manifest_epoch=header["manifest_epoch"];progress.manifest_revision=header["manifest_revision"]
        progress.source_content_version=None;progress.furthest_content_version=None;progress.furthest_chapter_key=None;progress.furthest_identity_inferred=0
        progress.furthest_chapter_number=0;progress.furthest_percent=0
        for key in ('block_id','text_quote','quote_prefix','quote_suffix','locator_content_version','locator_variant','device_id'):setattr(progress,key,None)
        progress.text_offset=0;progress.reading_run_key=run.run_key
    elif kind=='finish':
        mark_complete(db,run);run.status='completed'
    elif kind=='drop':
        run.status='abandoned';run.abandoned_at=now;run.abandon_reason=(value.reason or '').strip() or None
        event(db,run,'abandoned',when=now,reason=run.abandon_reason)
    progress.revision=(progress.revision or 0)+1
    db.flush();run.progress_snapshot=snapshot_progress(run,progress);db.flush()
    response=state(db,user_id,novel_id)
    # JSON receipts require dates as ISO strings; replay returns the same result.
    response=json.loads(json.dumps(response,default=lambda item:item.isoformat()))
    db.add(ReadingProgressOperation(user_id=user_id,novel_id=novel_id,operation_id=value.operation_id,fingerprint=signature,response=response))
    db.commit()
    return response


def journal(db,user_id,novel_id=None,offset=0,limit=50):
    if novel_id is not None:owned_story(db,user_id,novel_id)
    query=db.query(ReadingRunEvent,Novel.title,ReadingRun).join(Novel,Novel.id==ReadingRunEvent.novel_id).join(
        Library,Library.id==Novel.library_id).join(ReadingRun,ReadingRun.run_key==ReadingRunEvent.run_key).filter(
        ReadingRunEvent.user_id==user_id,Library.user_id==user_id)
    if novel_id is not None:query=query.filter(ReadingRunEvent.novel_id==novel_id)
    total=query.count()
    return dict(total=total,offset=offset,limit=limit,items=[dict(id=row.id,novel_id=row.novel_id,novel_title=title,
        reading_run_key=row.run_key,kind=row.kind,occurred_at=row.occurred_at,inferred=row.inferred,reason=row.reason,ordinal=display_ordinal(run))
        for row,title,run in query.order_by(ReadingRunEvent.id.desc()).offset(offset).limit(limit)])
