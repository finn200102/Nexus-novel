"""Additive personal reading-run archives, scoped to destination account/story."""
from datetime import UTC,datetime
from uuid import NAMESPACE_URL,uuid5
from app.models.reading_run import ReadingRun,ReadingRunEvent
from app.models.reading_progress import ReadingProgress
from app.models.reading_continuity import ReadingContinuity
from app.services import reading_continuity_service as continuity_service
from app.services.reading_run_service import current_run,display_ordinal,next_ordinal

DATE_FIELDS=('started_at','completed_at','abandoned_at','archived_at')
PROGRESS_FIELDS=('chapter_number','position','percent','furthest_chapter_number','furthest_percent','block_id','text_offset',
    'text_quote','quote_prefix','quote_suffix','locator_content_version','locator_variant')


def naive(value):
    return value.astimezone(UTC).replace(tzinfo=None) if value is not None and value.tzinfo else value


def iso(value):return value.isoformat() if value else None


def export_runs(db,user_id,novel_id):
    rows=db.query(ReadingRun).filter_by(user_id=user_id,novel_id=novel_id).order_by(ReadingRun.ordinal).all()
    events={}
    for event in db.query(ReadingRunEvent).filter_by(user_id=user_id,novel_id=novel_id).order_by(ReadingRunEvent.id):
        events.setdefault(event.run_key,[]).append(dict(kind=event.kind,occurred_at=iso(event.occurred_at),inferred=event.inferred,reason=event.reason))
    return [dict(reading_run_key=run.run_key,ordinal=display_ordinal(run),status=run.status,
        **continuity_export(db,run),
        **{field:iso(getattr(run,field)) for field in DATE_FIELDS},
        started_at_inferred=run.started_at_inferred,completed_at_inferred=run.completed_at_inferred,
        abandon_reason=run.abandon_reason,progress={field:run.progress_snapshot.get(field) for field in PROGRESS_FIELDS
            if run.progress_snapshot.get(field) is not None} if (run.progress_snapshot or {}).get('chapter_number') is not None else None,
        events=events.get(run.run_key,[])) for run in rows]


def import_runs(db,user,novel,item):
    """Never mutate native/live runs; stable remapping makes repeat imports safe."""
    existing_progress=db.query(ReadingProgress).filter_by(user_id=user.id,novel_id=novel.id).first()
    active=current_run(db,user.id,novel.id,existing_progress)
    can_restore=existing_progress is None and active is None
    selected=str(item.progress.reading_run_key) if item.progress and item.progress.reading_run_key else None
    mapping={};protected=set()
    report=dict(added=0,unchanged=0,kept_local=0,events_added=0,events_unchanged=0,inferred_events=0,current_restored=0)
    for incoming in sorted(item.reading_runs,key=lambda run:run.ordinal):
        source_key=str(incoming.reading_run_key)
        context=db.info.get('reading_continuity_import',{})
        if incoming.continuity is not None and context.get('user_id')==user.id and str(incoming.continuity.work_key) in context.get('blocked_work',set()):
            report['kept_local']+=1;continue
        # An own-instance reimport recognizes a native key only within this
        # exact owned story. It never uses someone else's UUID as an authority.
        native=db.query(ReadingRun).filter_by(user_id=user.id,novel_id=novel.id,run_key=source_key).first()
        key=source_key if native else str(uuid5(NAMESPACE_URL,f'nexus-portable-run:{user.storage_id}:{novel.id}:{source_key}'))
        row=native or db.query(ReadingRun).filter_by(run_key=key).first()
        if row is not None and (row.user_id!=user.id or row.novel_id!=novel.id):
            report['kept_local']+=1;continue
        mapping[source_key]=key
        is_live=row is not None and (not row.archived_at or not (row.progress_snapshot or {}).get('_portable_source_key'))
        if is_live:
            protected.add(key);report['kept_local']+=1
            continue
        if row is None:
            restoring=can_restore and source_key==selected
            snapshot=incoming.progress.model_dump(mode='json',exclude={'reading_run_key'}) if incoming.progress else {}
            snapshot.update(novel_id=novel.id,reading_run_key=key,revision=0,
                _portable_ordinal=incoming.ordinal,_portable_source_key=source_key)
            row=ReadingRun(user_id=user.id,novel_id=novel.id,run_key=key,ordinal=next_ordinal(db,user.id,novel.id),status=incoming.status,
                requires_run_key=True,progress_snapshot=snapshot,
                started_at=naive(incoming.started_at),started_at_inferred=incoming.started_at_inferred or incoming.started_at is None,
                completed_at=naive(incoming.completed_at),completed_at_inferred=incoming.completed_at_inferred or (incoming.status=='completed' and incoming.completed_at is None),
                abandoned_at=naive(incoming.abandoned_at),abandon_reason=incoming.abandon_reason,
                archived_at=None if restoring else naive(incoming.archived_at) or datetime.now(UTC).replace(tzinfo=None))
            db.add(row);db.flush();report['added']+=1
            if restoring:report['current_restored']=1
        else:
            report['unchanged']+=1
            if can_restore and source_key==selected:
                row.archived_at=None;row.requires_run_key=True;report['current_restored']=1
        attach_continuity(db,user,novel,row,incoming,report)
        known={(event.kind,event.occurred_at,event.inferred,event.reason) for event in db.query(ReadingRunEvent).filter_by(
            user_id=user.id,novel_id=novel.id,run_key=key)}
        facts=[event.model_dump() for event in incoming.events]
        # A legacy/incomplete export may retain a completion fact on the run
        # without its event. Preserve it as undated instead of making up a date.
        if incoming.continuity is None and (incoming.completed_at is not None or incoming.completed_at_inferred or incoming.status=='completed') and not any(fact['kind']=='completed' for fact in facts):
            facts.append(dict(kind='completed',occurred_at=incoming.completed_at,inferred=incoming.completed_at_inferred or incoming.completed_at is None,reason=None))
        if not any(fact['kind']=='started' for fact in facts):facts.insert(0,dict(kind='started',occurred_at=incoming.started_at,inferred=incoming.started_at_inferred or incoming.started_at is None,reason=None))
        if incoming.abandoned_at is not None and not any(fact['kind']=='abandoned' for fact in facts):facts.append(dict(kind='abandoned',occurred_at=incoming.abandoned_at,inferred=False,reason=incoming.abandon_reason))
        for fact in facts:
            when=naive(fact['occurred_at']);inferred=bool(fact['inferred'] or when is None)
            signature=(fact['kind'],when,inferred,fact['reason'])
            if signature in known:report['events_unchanged']+=1;continue
            db.add(ReadingRunEvent(user_id=user.id,novel_id=novel.id,run_key=key,kind=fact['kind'],occurred_at=when,inferred=inferred,reason=fact['reason']))
            known.add(signature);report['events_added']+=1;report['inferred_events']+=int(inferred)
        db.flush()
        if incoming.continuity is None:
            continuity_service.ensure_continuity(db,row)
    return mapping,protected,report



def continuity_export(db,run):
    if not run.continuity_key:return {}
    group=db.query(ReadingContinuity).filter_by(user_id=run.user_id,continuity_key=run.continuity_key).first()
    if group is None:return {}
    return {'continuity':{'key':group.continuity_key,'work_key':group.work_key,'logical_ordinal':group.logical_ordinal,
        'completion':{'occurred_at':iso(group.completed_at),'inferred':group.completed_at_inferred} if group.completed else None}}


def attach_continuity(db,user,novel,row,incoming,report):
    value=incoming.continuity
    if value is None:return
    source_key=str(value.key)
    native=db.query(ReadingContinuity).filter_by(user_id=user.id,continuity_key=source_key).first()
    key=native.continuity_key if native else str(uuid5(NAMESPACE_URL,f'nexus-portable-continuity:{user.storage_id}:{source_key}'))
    group=native or db.query(ReadingContinuity).filter_by(continuity_key=key).first()
    if group is not None and group.user_id!=user.id:
        raise ValueError('Reading continuity identity conflicts with another account')
    if row.continuity_key and row.continuity_key!=key:
        report['kept_local']+=1;return
    if group is None:
        source_work=str(value.work_key)
        native_work=db.query(ReadingContinuity.work_key).filter_by(user_id=user.id,work_key=source_work).first()
        same_story=db.query(ReadingContinuity.work_key).join(ReadingRun,ReadingRun.continuity_key==ReadingContinuity.continuity_key).filter(
            ReadingContinuity.user_id==user.id,ReadingRun.user_id==user.id,ReadingRun.novel_id==novel.id).first()
        mapped_work=str(uuid5(NAMESPACE_URL,f'nexus-portable-work:{user.storage_id}:{source_work}'))
        existing_mapped=db.query(ReadingContinuity.work_key).filter_by(user_id=user.id,work_key=mapped_work).first()
        context=db.info.get('reading_continuity_import',{})
        approved=context.get('work_map',{}).get(source_work) if context.get('user_id')==user.id else None
        work=approved or (native_work[0] if native_work else existing_mapped[0] if existing_mapped else same_story[0] if same_story else mapped_work)
        fact=value.completion
        group=ReadingContinuity(user_id=user.id,continuity_key=key,work_key=work,logical_ordinal=value.logical_ordinal,
            completed=fact is not None,completed_at=naive(fact.occurred_at) if fact else None,
            completed_at_inferred=bool(fact.inferred or fact.occurred_at is None) if fact else False,
            completion_novel_id=novel.id if fact else None)
        db.add(group);db.flush()
    elif value.completion is not None and not group.completed and native is None:
        members=db.query(ReadingRun).filter_by(user_id=user.id,continuity_key=key).all()
        if all(member.archived_at is not None and (member.progress_snapshot or {}).get('_portable_source_key') for member in members):
            group.completed=True;group.completed_at=naive(value.completion.occurred_at)
            group.completed_at_inferred=bool(value.completion.inferred or value.completion.occurred_at is None)
            group.completion_novel_id=novel.id
        else:report['kept_local']+=1
    row.progress_snapshot={**(row.progress_snapshot or {}),'_portable_work_key':str(value.work_key)}
    row.continuity=group
    row.continuity_key=key



def prepare_import(db,user,document):
    """Resolve private work aliases before entry order can affect shared groups.

    Conflicting local identities are kept local, never silently merged by an
    incoming file. Source URLs/library names use the existing import resolver.
    """
    from app.models import Novel,Library
    candidates={}
    known={(name,url):novel_id for name,url,novel_id in db.query(Library.name,Novel.url,Novel.id).join(Novel).filter(Library.user_id==user.id) if url is not None}
    aliases={}
    for snapshot,work in db.query(ReadingRun.progress_snapshot,ReadingContinuity.work_key).join(
        ReadingContinuity,ReadingContinuity.continuity_key==ReadingRun.continuity_key).filter(
        ReadingRun.user_id==user.id,ReadingContinuity.user_id==user.id):
        alias=(snapshot or {}).get('_portable_work_key')
        if isinstance(alias,str):aliases.setdefault(alias,set()).add(work)
    for library in document.libraries:
        for item in library.novels:
            if item.url is None:
                from app.services.portable_story_service import find_existing
                local_library=db.query(Library).filter_by(user_id=user.id,name=library.name).first()
                target=find_existing(db,user,local_library,item.portable_story)
                novel_id=target.id if target else None
            else:novel_id=known.get((library.name,item.url))
            existing=set()
            if novel_id is not None:
                existing={work for (work,) in db.query(ReadingContinuity.work_key).join(
                    ReadingRun,ReadingRun.continuity_key==ReadingContinuity.continuity_key).filter(
                    ReadingContinuity.user_id==user.id,ReadingRun.user_id==user.id,ReadingRun.novel_id==novel_id)}
            for incoming in item.reading_runs:
                if incoming.continuity is None:continue
                source=str(incoming.continuity.work_key)
                choices=candidates.setdefault(source,set());choices.update(existing);choices.update(aliases.get(source,set()))
                native=db.query(ReadingContinuity.work_key).filter_by(user_id=user.id,work_key=source).first()
                if native:choices.add(native[0])
    db.info['reading_continuity_import']={'user_id':user.id,
        'work_map':{source:next(iter(values)) for source,values in candidates.items() if len(values)==1},
        'blocked_work':{source for source,values in candidates.items() if len(values)>1}}
