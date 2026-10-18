"""Account-owned logical readings, independent of story-local run identity."""
from datetime import datetime
from uuid import NAMESPACE_URL, uuid5
from fastapi import HTTPException
from sqlalchemy import func, update
from app.models.reading_continuity import ReadingContinuity
from app.models.reading_run import ReadingRun, ReadingRunEvent
from app.models import User, Novel, Library
from app.services.job_lease import utcnow


def work_key(db, user_id, novel_id):
    existing = db.query(ReadingContinuity.work_key).join(ReadingRun,ReadingRun.continuity_key==ReadingContinuity.continuity_key).join(
        Novel,Novel.id==ReadingRun.novel_id).join(Library,Library.id==Novel.library_id).filter(
        ReadingContinuity.user_id==user_id,ReadingRun.user_id==user_id,ReadingRun.novel_id==novel_id,Library.user_id==user_id).order_by(ReadingRun.id).first()
    if existing:return existing[0]
    identity = db.query(User.storage_id).filter_by(id=user_id).scalar()
    return str(uuid5(NAMESPACE_URL, f'nexus-reading-work:{identity}:{novel_id}'))


def ordinal_of(run):
    value = (run.progress_snapshot or {}).get('_portable_ordinal')
    return value if type(value) is int and value > 0 else run.ordinal


def ensure_continuity(db, run, *, work=None, logical_ordinal=None):
    if run.continuity_key:
        row = db.query(ReadingContinuity).filter_by(user_id=run.user_id, continuity_key=run.continuity_key).first()
        if row is None:raise HTTPException(409, 'This reading continuity is unavailable for this account')
        return row
    key = run.run_key
    row = db.query(ReadingContinuity).filter_by(continuity_key=key).first()
    if row is not None and row.user_id != run.user_id:raise HTTPException(409, 'Reading continuity identifier conflict')
    if row is None:
        row = ReadingContinuity(user_id=run.user_id, continuity_key=key,
            work_key=work or work_key(db,run.user_id,run.novel_id), logical_ordinal=logical_ordinal or ordinal_of(run), completed=False)
        # Legacy raw/fixture runs may not yet carry an upgraded membership.
        facts = db.query(ReadingRunEvent).filter_by(user_id=run.user_id, novel_id=run.novel_id, run_key=run.run_key, kind='completed').all()
        facts.sort(key=lambda fact:(bool(fact.inferred or fact.occurred_at is None),fact.occurred_at or datetime.max))
        if facts:
            fact=facts[0];row.completed=True;row.completed_at=fact.occurred_at
            row.completed_at_inferred=bool(fact.inferred or fact.occurred_at is None);row.completion_novel_id=run.novel_id
        db.add(row);db.flush()
    run.continuity=row
    run.continuity_key=row.continuity_key
    return row


def new_reading(db,run,previous=None):
    """Explicit Start again creates a new logical attempt of the same work."""
    db.query(User).filter_by(id=run.user_id).with_for_update().first()
    if previous is None:return ensure_continuity(db,run)
    parent=ensure_continuity(db,previous)
    maximum=db.query(func.max(ReadingContinuity.logical_ordinal)).filter_by(user_id=run.user_id,work_key=parent.work_key).scalar() or 0
    return ensure_continuity(db,run,work=parent.work_key,logical_ordinal=maximum+1)


def join_new_run(db,source_run,target_run):
    """Internal foundation only: join a fresh target; no fetching or commit.

    Positions and run keys remain story-local. Both copies continue one logical
    reading until an explicit Start again creates a new continuity.
    """
    if source_run.user_id != target_run.user_id or source_run.novel_id == target_run.novel_id:
        raise HTTPException(409,'Continuation requires two different owned story copies')
    db.query(User).filter_by(id=source_run.user_id).with_for_update().first()
    for run in (source_run,target_run):
        owned=db.query(Novel.id).join(Library).filter(Novel.id==run.novel_id,Library.user_id==run.user_id).first()
        if owned is None:raise HTTPException(404,'Story not found')
    from app.models.reading_progress import ReadingProgress
    from app.models.reading_history import ReadingHistory
    if (target_run.progress_snapshot or {}).get('chapter_number') is not None or (target_run.progress_snapshot or {}).get('revision',0):
        raise HTTPException(409,'The target run already has reading progress')
    if db.query(ReadingProgress.id).filter_by(user_id=target_run.user_id,reading_run_key=target_run.run_key).first() or db.query(ReadingHistory.id).filter_by(user_id=target_run.user_id,reading_run_key=target_run.run_key).first():
        raise HTTPException(409,'The target run already has reading progress or history')
    if target_run.completed_at or target_run.completed_at_inferred or target_run.status!='active':
        raise HTTPException(409,'Only a new target reading run can join this continuity')
    if target_run.id is not None and db.query(ReadingRunEvent.id).filter_by(user_id=target_run.user_id,run_key=target_run.run_key).first():
        raise HTTPException(409,'The target run already has reading history')
    group=ensure_continuity(db,source_run)
    if target_run.continuity_key and target_run.continuity_key != group.continuity_key:
        own=ensure_continuity(db,target_run)
        if own.completed or db.query(ReadingRun.id).filter(ReadingRun.continuity_key==own.continuity_key,ReadingRun.id!=target_run.id).first():raise HTTPException(409,'The target run already has a completion')
    target_run.continuity=group
    target_run.continuity_key=group.continuity_key
    return group


def complete(db,run,*,inferred=False):
    """First completion is immutable; sibling finishes reuse the same fact."""
    db.query(User).filter_by(id=run.user_id).with_for_update().first()
    group=ensure_continuity(db,run)
    # Database CAS is also required on SQLite, where FOR UPDATE is advisory.
    db.execute(update(ReadingContinuity).where(ReadingContinuity.continuity_key==group.continuity_key,
        ReadingContinuity.user_id==run.user_id,ReadingContinuity.completed.is_(False)).values(
        completed=True,completed_at=None if inferred else utcnow(),completed_at_inferred=inferred,
        completion_novel_id=run.novel_id).execution_options(synchronize_session=False))
    db.refresh(group)
    run.status='completed';run.completed_at=group.completed_at;run.completed_at_inferred=group.completed_at_inferred
    if not db.query(ReadingRunEvent.id).filter_by(user_id=run.user_id,run_key=run.run_key,kind='completed').first():
        db.add(ReadingRunEvent(user_id=run.user_id,novel_id=run.novel_id,run_key=run.run_key,kind='completed',
            occurred_at=group.completed_at,inferred=group.completed_at_inferred,reason=None))
    return group


def completion_rows(db,user_id):
    """Small canonical facts, with attribution only to surviving owned members."""
    members=db.query(ReadingRun.continuity_key,ReadingRun.novel_id).join(Novel,Novel.id==ReadingRun.novel_id).join(
        Library,Library.id==Novel.library_id).filter(ReadingRun.user_id==user_id,Library.user_id==user_id,
            ReadingRun.continuity_key.isnot(None)).all()
    owned={}
    for key,novel_id in members:owned.setdefault(key,set()).add(novel_id)
    if not owned:return []
    # Avoid an unbounded SQL IN parameter list for large histories.
    groups=db.query(ReadingContinuity).filter_by(user_id=user_id,completed=True).all()
    return [(row.continuity_key,row.completion_novel_id if row.completion_novel_id in owned[row.continuity_key] else min(owned[row.continuity_key]),
        row.completed_at,row.completed_at_inferred,row.logical_ordinal,{'_continuity_work_key':row.work_key})
        for row in groups if row.continuity_key in owned]
