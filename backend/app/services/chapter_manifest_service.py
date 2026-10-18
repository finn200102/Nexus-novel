"""Owned manifest observations and explicit topology reviews."""
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from sqlalchemy import func
from app.models.chapter_manifest import ChapterManifestReview, ChapterManifestReviewItem
from app.models.reading_progress import ReadingProgress
from app.models.reading_history import ReadingHistory
from app.models.chapter_read_receipt import ChapterReadReceipt
from app.services import metadata_client

from jose import jwt, JWTError
from sqlalchemy import or_, and_
from fastapi import HTTPException
from app.models import User, Novel, Library, Chapter
from app.models.account import UserSession
from app.services.chapter_identity_service import manifest_state, state_fields, conflict, sqlite_transaction
from config.settings import settings


def owner(db,user_id,novel_id,session_id=None,*,lock=False):
    db.expire_all()
    query=db.query(User).filter_by(id=user_id).populate_existing()
    if lock:query=query.with_for_update()
    user=query.first()
    if user is None or user.is_disabled:raise HTTPException(401,'Account is unavailable')
    from app.auth.dependencies import require_current_session
    require_current_session(db,user_id)
    if session_id is not None:
        session=db.query(UserSession).filter_by(id=session_id,user_id=user_id).populate_existing().first()
        if session is None or session.revoked_at is not None:raise HTTPException(401,'Session ended. Sign in again.')
    query=db.query(Novel).join(Library).filter(Novel.id==novel_id,Library.user_id==user_id).populate_existing()
    if lock:query=query.with_for_update(of=Novel)
    novel=query.first()
    if novel is None:raise HTTPException(404,'Story not found')
    return user,novel


def state_page(db,user_id,novel_id,*,session_id=None,limit=200,cursor=None,expected_manifest_epoch=None,expected_manifest_revision=None):
    if not 1<=limit<=1000:raise HTTPException(422,'Choose a page size between 1 and 1000')
    sqlite_transaction(db)
    owner(db,user_id,novel_id,session_id)
    state=manifest_state(db,novel_id,lock=True)
    header=state_fields(state)
    if expected_manifest_epoch is not None and expected_manifest_epoch!=header['manifest_epoch'] or expected_manifest_revision is not None and expected_manifest_revision!=header['manifest_revision']:
        conflict('chapter_manifest_changed','The chapter list changed. Restart this manifest observation.',header)
    query=db.query(Chapter.id,Chapter.chapter_key,Chapter.chapter_number,Chapter.title,
        Chapter.document['content_version'].as_string().label('source_version')).filter(Chapter.novel_id==novel_id)
    total=query.count()
    if cursor is not None:
        if expected_manifest_epoch is None or expected_manifest_revision is None:
            conflict('chapter_identity_required','Continue the manifest with its captured epoch and revision.',header)
        try:
            token=jwt.decode(cursor,settings.SECRET_KEY,algorithms=[settings.ALGORITHM])
        except JWTError as exc:raise HTTPException(422,'Invalid chapter manifest cursor') from exc
        if token.get('purpose')!='local-chapter-manifest-v1' or token.get('user')!=user_id or token.get('novel')!=novel_id or token.get('epoch')!=header['manifest_epoch'] or token.get('revision')!=header['manifest_revision']:
            conflict('chapter_manifest_changed','This cursor belongs to a different manifest. Restart the chapter list.',header)
        number,id=token.get('number'),token.get('id')
        if type(number) is not int or not -(2**31)<=number<2**31 or type(id) is not int or id<=0:
            raise HTTPException(422,'Invalid chapter manifest cursor')
        query=query.filter(or_(Chapter.chapter_number>number,and_(Chapter.chapter_number==number,Chapter.id>id)))
    rows=query.order_by(Chapter.chapter_number,Chapter.id).limit(limit+1).all()
    more=len(rows)>limit;rows=rows[:limit]
    next_cursor=None
    if more:
        last=rows[-1]
        next_cursor=jwt.encode({'purpose':'local-chapter-manifest-v1','user':user_id,'novel':novel_id,
            'epoch':header['manifest_epoch'],'revision':header['manifest_revision'],'number':last.chapter_number,'id':last.id},
            settings.SECRET_KEY,algorithm=settings.ALGORITHM)
    result=dict(novel_id=novel_id,**header,identity_required=state.identity_required,total=total,
        items=[dict(id=row.id,chapter_key=row.chapter_key,chapter_number=row.chapter_number,title=row.title,
                    source_version=row.source_version,archived=False,**header) for row in rows],next_cursor=next_cursor,has_more=more)
    db.rollback()
    return result


def resolve_key(db,user_id,novel_id,chapter_key,session_id=None):
    sqlite_transaction(db)
    owner(db,user_id,novel_id,session_id)
    state=manifest_state(db,novel_id,lock=True)
    row=db.query(Chapter.id,Chapter.chapter_key,Chapter.chapter_number,Chapter.title,Chapter.archived,
        Chapter.document['content_version'].as_string().label('source_version')).execution_options(include_archived_chapters=True).filter(
            Chapter.novel_id==novel_id,Chapter.chapter_key==chapter_key).first()
    if row is None:raise HTTPException(404,'Chapter identity not found')
    result=dict(id=row.id,chapter_key=row.chapter_key,chapter_number=row.chapter_number,title=row.title,
                source_version=row.source_version,archived=row.archived,**state_fields(state))
    db.rollback()
    return result


# Reviews own no chapter bodies. Their immutable pages keep a large manifest
# out of a single browser response and are invalidated by exact private state.

MAX_CHAPTERS = 200_000


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),default=str).encode()).hexdigest()


def _source(novel):
    return {key:getattr(novel,key) for key in ('metadata_id','site','novel_site','site_story_id','story_id','source_url','url','library_id')}


def ao3_source(source):
    from urllib.parse import urlsplit
    if str(source.get('site') or '').casefold() in ('ao3','archive'):return True
    return (urlsplit(source.get('source_url') or '').hostname or '').casefold() in ('archiveofourown.org','www.archiveofourown.org')


def known_source_matches(novel,source):
    def canonical(site):return 'archive' if str(site or '').casefold()=='ao3' else str(site or '').casefold()
    for site in (novel.site,novel.novel_site):
        if site is not None and canonical(site)!=canonical(source.get('site')):return False
    for story_id in (novel.site_story_id,novel.story_id):
        if story_id not in (None,0) and story_id!=source.get('story_id'):return False
    return novel.source_url is None or novel.source_url==source.get('source_url')


def _private_digest(db,user_id,novel_id):
    from config.database import Base
    from app.services.source_migration_service import rows_state
    state={}
    for mapper in sorted(Base.registry.mappers,key=lambda m:m.local_table.name):
        model=mapper.class_
        if model.__tablename__.startswith('chapter_manifest_'):continue
        if hasattr(model,'novel_id'):
            query=db.query(model).execution_options(include_archived_chapters=True).filter(model.novel_id==novel_id)
            if hasattr(model,'user_id'):query=query.filter(model.user_id==user_id)
        elif hasattr(model,'chapter_id'):
            query=db.query(model).execution_options(include_archived_chapters=True).join(Chapter,Chapter.id==model.chapter_id).filter(Chapter.novel_id==novel_id)
            if hasattr(model,'user_id'):query=query.filter(model.user_id==user_id)
        else:continue
        state[model.__tablename__]=rows_state(query.populate_existing())
    from app.models.reading_run import ReadingRun
    from app.models.reading_continuity import ReadingContinuity
    groups=db.query(ReadingRun.continuity_key).filter_by(user_id=user_id,novel_id=novel_id).filter(ReadingRun.continuity_key.is_not(None))
    state['private_source']=_source(db.query(Novel).filter_by(id=novel_id).one())
    state['canonical_readings']=rows_state(db.query(ReadingContinuity).populate_existing().filter(ReadingContinuity.user_id==user_id,ReadingContinuity.continuity_key.in_(groups)))
    manifest=manifest_state(db,novel_id)
    state["manifest_header"]={**state_fields(manifest),**{key:getattr(manifest,key) for key in ('metadata_source','metadata_manifest_key','metadata_revision','metadata_fingerprint')}}
    return _hash(state)



def _point(db,user_id,novel_id):
    from app.services.reading_run_service import current_run,restore_progress
    point=db.query(ReadingProgress).filter_by(user_id=user_id,novel_id=novel_id).first()
    return point if point is not None else restore_progress(current_run(db,user_id,novel_id))


def _active(db,user_id,novel_id):
    from config.database import Base
    for mapper in sorted(Base.registry.mappers,key=lambda m:m.local_table.name):
        model=mapper.class_
        if not all(hasattr(model,key) for key in ('novel_id','status','user_id')):continue
        if db.query(model.id).filter(model.novel_id==novel_id,model.user_id==user_id,
            model.status.in_(('queued','processing','running','retry_wait','pending','cancelling'))).first():
            return True
    return db.query(Chapter.id).filter(Chapter.novel_id==novel_id,or_(Chapter.content_status=='PROCESSING',Chapter.audio_status=='PROCESSING')).first() is not None


def _review(db,user_id,novel_id,review_id):
    row=db.query(ChapterManifestReview).filter_by(id=review_id,user_id=user_id,novel_id=novel_id).first()
    if row is None:raise HTTPException(404,'Chapter review not found')
    return row


def _item_page(db,row,kind,offset=0,limit=200):
    if offset<0 or not 1<=limit<=200:raise HTTPException(422,'Invalid review page')
    query=db.query(ChapterManifestReviewItem).filter_by(review_id=row.id,item_kind=kind)
    total=query.count()
    items=[item.detail for item in query.order_by(ChapterManifestReviewItem.ordinal).offset(offset).limit(limit)]
    return dict(review_id=row.id,items=items,total=total,offset=offset,limit=limit,has_more=offset+len(items)<total)


def _token(row):
    return jwt.encode({'purpose':'chapter-topology-review-v1','review':row.id,'user':row.user_id,
        'key':row.review_key,'fingerprint':row.fingerprint,'exp':row.expires_at},settings.SECRET_KEY,algorithm=settings.ALGORITHM)


def _view(db,row,*,current_digest=None,active_work=None):
    header=state_fields(manifest_state(db,row.novel_id))
    plan=row.plan
    blockers=list(plan['blocked_reasons'])
    try:
        from app.services.chapter_topology_guards import TOPOLOGY_GUARDS_COMPLETE
    except ImportError:
        TOPOLOGY_GUARDS_COMPLETE=False
    if not TOPOLOGY_GUARDS_COMPLETE:
        blockers.append({'code':'topology_guards_incomplete','message':'Chapter-list updates are awaiting complete derivative and evidence integration.'})
    if current_digest is None:current_digest=_private_digest(db,row.user_id,row.novel_id)
    unchanged=current_digest==row.fingerprint
    active=_active(db,row.user_id,row.novel_id) if active_work is None else active_work
    if row.status=='preview' and not unchanged:blockers.append({'code':'review_stale','message':'Reading state or chapter content changed. Build a fresh review.'})
    if active:blockers.append({'code':'active_work','message':'Wait for active downloads and generated work before changing the chapter list.'})
    can_undo=TOPOLOGY_GUARDS_COMPLETE and row.status=='applied' and not active and row.after_fingerprint==current_digest
    return dict(review_id=row.id,revision=row.revision,status=row.status,review_token=_token(row),novel_id=row.novel_id,
        **header,reviewed_manifest_epoch=plan['reviewed_manifest_epoch'],reviewed_manifest_revision=plan['reviewed_manifest_revision'],
        anchors=plan['anchors'],expires_at=row.expires_at.isoformat()+'Z',remote=plan['remote'],counts=plan['counts'],
        items=_item_page(db,row,'items'),unmapped=_item_page(db,row,'unmapped'),blocked_reasons=blockers,
        can_apply=row.status=='preview' and datetime.now(UTC).replace(tzinfo=None)<row.expires_at and not blockers,
        can_undo=can_undo,undo_blocked_reason=None if can_undo else 'Undo requires unchanged transferred state and no active work.')


def review_view(db,user_id,novel_id,review_id,*,session_id=None):
    sqlite_transaction(db)
    owner(db,user_id,novel_id,session_id)
    result=_view(db,_review(db,user_id,novel_id,review_id));db.rollback();return result


def review_page(db,user_id,novel_id,*,session_id=None,offset=0,limit=20):
    if offset<0 or not 1<=limit<=50:raise HTTPException(422,'Invalid review page')
    sqlite_transaction(db);owner(db,user_id,novel_id,session_id)
    query=db.query(ChapterManifestReview).filter_by(user_id=user_id,novel_id=novel_id)
    total=query.count();rows=query.order_by(ChapterManifestReview.id.desc()).offset(offset).limit(limit).all()
    current_digest=_private_digest(db,user_id,novel_id) if rows else None
    active=_active(db,user_id,novel_id) if rows else False
    result=dict(items=[_view(db,row,current_digest=current_digest,active_work=active) for row in rows],total=total,offset=offset,limit=limit,has_more=offset+len(rows)<total)
    db.rollback();return result


def review_items(db,user_id,novel_id,review_id,*,session_id=None,kind='items',offset=0,limit=200):
    if kind not in ('items','unmapped'):raise HTTPException(422,'Unknown review item kind')
    sqlite_transaction(db);owner(db,user_id,novel_id,session_id)
    result=_item_page(db,_review(db,user_id,novel_id,review_id),kind,offset,limit);db.rollback();return result


def remote_choices(db,user_id,novel_id,review_id,*,session_id=None,q='',ids=(),offset=0,limit=100):
    if offset<0 or not 1<=limit<=200 or len(ids)>100 or len(q)>200:raise HTTPException(422,'Invalid source chapter lookup')
    sqlite_transaction(db);owner(db,user_id,novel_id,session_id);row=_review(db,user_id,novel_id,review_id)
    query=db.query(ChapterManifestReviewItem).filter_by(review_id=row.id,item_kind='remote')
    if ids:query=query.filter(ChapterManifestReviewItem.metadata_chapter_key.in_(ids))
    if q:query=query.filter(ChapterManifestReviewItem.title.ilike('%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%',escape='\\'))
    total=query.count();items=[item.detail for item in query.order_by(ChapterManifestReviewItem.ordinal).offset(offset).limit(limit)]
    result=dict(review_id=row.id,items=items,total=total,offset=offset,limit=limit,has_more=offset+len(items)<total)
    db.rollback();return result


def _archive_context(remote,state,namespace_changed):
    keys={item['chapter_key'] for item in remote.items}
    return dict(accepted=bool(remote.complete and remote.source_complete and remote.deletion_authoritative and
        remote.source_capture_id is not None and remote.source_authority_kind in ('adapter_stable','reviewed_mapping') and
        (remote.source_authority_kind!='reviewed_mapping' or remote.source_review_id is not None)),
        same_source=not namespace_changed and state.metadata_source==remote.source and state.metadata_manifest_key==remote.manifest_key,
        manifest_key=remote.manifest_key,remote_keys=keys,
        stable_ids={item['chapter_id'] for item in remote.items if item['identity_kind']=='stable_source_id'},
        present_lineage={item['old_chapter_key'] for item in getattr(remote,'source_lineage',[]) if item.get('old_chapter_key') and item.get('new_chapter_key') in keys})


def _archive_reason(chapter,context):
    if chapter.archived:return 'source_absence_unproven','This original is already preserved in the archive.'
    if not context['accepted']:
        return 'source_absence_unproven','Archival needs a complete, accepted source capture. A catalog snapshot cannot prove a chapter is absent.'
    if not context['same_source']:
        return 'source_absence_unproven','Archival requires the unchanged, previously bound source namespace.'
    if chapter.metadata_manifest_key!=context['manifest_key'] or chapter.metadata_chapter_key is None:
        return 'source_absence_unproven','Bind this original to its reviewed source identity before deciding it is absent.'
    if chapter.metadata_chapter_key in context['remote_keys'] or chapter.metadata_chapter_key in context['present_lineage'] or chapter.site_chapter_id in context['stable_ids']:
        return 'source_chapter_still_present','This original is still present in the accepted source capture. Keep or explicitly map it.'
    return None


def _archive_selection(keys,by_key,remote,state,namespace_changed,*,context=None):
    if len(keys)!=len(set(keys)):raise HTTPException(422,'Choose each chapter to archive only once.')
    selected=set(keys)
    if any(key not in by_key or by_key[key].archived for key in selected):
        raise HTTPException(422,'Only active chapters belonging to this exact story can be archived.')
    if not selected:return selected
    context=context or _archive_context(remote,state,namespace_changed)
    for key in selected:
        reason=_archive_reason(by_key[key],context)
        if reason:raise HTTPException(422,detail={'code':reason[0],'message':reason[1]})
    return selected


async def preview(db,user_id,novel_id,value,*,session_id=None):
    _,novel=owner(db,user_id,novel_id,session_id)
    source=_source(novel);before=state_fields(manifest_state(db,novel_id))
    if value.expected_manifest_epoch!=before['manifest_epoch'] or value.expected_manifest_revision!=before['manifest_revision']:
        conflict('chapter_manifest_changed','Refresh the chapter list before reviewing it.',before)
    if source['metadata_id'] is None:raise HTTPException(422,'Link a recognized source before reviewing its chapter list.')
    db.rollback()  # Remote paging never owns a database lock or transaction.
    try:remote=await metadata_client.get_chapter_manifest(source['metadata_id'],force_refresh=True)
    except metadata_client.ChapterManifestError as exc:raise HTTPException(409 if exc.retryable else 422,detail={'code':exc.category,'message':str(exc)}) from exc
    sqlite_transaction(db,write=True)
    _,novel=owner(db,user_id,novel_id,session_id,lock=True)
    local_state=manifest_state(db,novel_id)
    header=state_fields(local_state)
    namespace_changed=(local_state.metadata_source is not None and local_state.metadata_source!=remote.source) or not known_source_matches(novel,remote.source)
    if _source(novel)!=source or header!=before:conflict('chapter_manifest_changed','Source or local chapters changed while loading. Build a fresh review.',header)
    query=db.query(Chapter.id,Chapter.chapter_key,Chapter.chapter_number,Chapter.title,Chapter.site_chapter_id,
        Chapter.metadata_manifest_key,Chapter.metadata_chapter_key,Chapter.archived,Chapter.archived_at).execution_options(include_archived_chapters=True).filter(Chapter.novel_id==novel_id)
    if query.count()>MAX_CHAPTERS:raise HTTPException(422,'This review supports at most 200,000 local chapters.')
    local=query.order_by(Chapter.chapter_number,Chapter.id).all();by_key={r.chapter_key:r for r in local}
    remote_by_key={r['chapter_key']:r for r in remote.items}
    archive_context=_archive_context(remote,local_state,namespace_changed)
    archive_keys=_archive_selection(value.archive_chapter_keys,by_key,remote,local_state,namespace_changed,context=archive_context)
    lineage={}
    for item in getattr(remote,'source_lineage',[]):
        if item.get('old_chapter_key') and item.get('new_chapter_key') in remote_by_key:
            lineage.setdefault(item['old_chapter_key'],set()).add(item['new_chapter_key'])
    mappings={};confirm=set()
    for mapping in value.mappings:
        if mapping.chapter_key not in by_key or mapping.metadata_chapter_key not in remote_by_key:raise HTTPException(422,'A selected chapter does not belong to this exact local/source snapshot.')
        if mapping.chapter_key in archive_keys:raise HTTPException(422,'A chapter cannot be both mapped and archived.')
        if mapping.chapter_key in mappings:raise HTTPException(422,'Choose one source chapter for each local chapter.')
        mappings[mapping.chapter_key]=mapping.metadata_chapter_key
        if mapping.confirm_inferred_anchors:confirm.add(mapping.chapter_key)
    if len(set(mappings.values()))!=len(mappings):raise HTTPException(422,'A source chapter cannot replace two local chapters.')
    explicit=set(mappings)
    revivable=_revivable_archives(db,user_id,novel_id,remote.manifest_key)
    # Audited source IDs are scoped to the full captured metadata work. Titles
    # and numeric positions never supply identity, even when text is identical.
    namespace_ok=remote.source.get('site') in (source['site'],source['novel_site']) and remote.source.get('story_id') in (source['site_story_id'],source['story_id']) and remote.source.get('story_id') is not None
    stable={}
    for item in remote.items:
        if item['identity_kind']=='stable_source_id':stable.setdefault(item['chapter_id'],[]).append(item)
    local_source_counts={}
    for item in local:local_source_counts[item.site_chapter_id]=local_source_counts.get(item.site_chapter_id,0)+1
    decisions={}
    occupied=set(mappings.values())
    for item in local:
        if item.chapter_key in mappings:decisions[item.chapter_key]='explicit';continue
        if item.archived or item.chapter_key in archive_keys:continue
        candidates=[]
        if item.metadata_manifest_key==remote.manifest_key and item.metadata_chapter_key in remote_by_key:
            candidates=[remote_by_key[item.metadata_chapter_key]];decision='bound'
        elif item.metadata_chapter_key in lineage:continue  # Reviewed lineage is a suggestion, never an automatic binding.
        elif namespace_ok and item.site_chapter_id is not None and local_source_counts[item.site_chapter_id]==1:
            candidates=stable.get(item.site_chapter_id,[]);decision='stable_source_id'
        if len(candidates)==1 and candidates[0]['chapter_key'] not in occupied:
            mappings[item.chapter_key]=candidates[0]['chapter_key'];decisions[item.chapter_key]=decision;occupied.add(candidates[0]['chapter_key'])
    for remote_key,local_key in revivable.items():
        if local_key in by_key and local_key not in mappings and local_key not in archive_keys and remote_key not in occupied:
            mappings[local_key]=remote_key;decisions[local_key]='bound';occupied.add(remote_key)
    point=_point(db,user_id,novel_id)
    anchors=[];blockers=[]
    if point:
        for kind,key,number,percent,inferred,version,resolved_key in (
            ('current',point.chapter_key,point.chapter_number,point.percent,point.current_identity_inferred,point.source_content_version,value.resolve_current_chapter_key),
            ('furthest',point.furthest_chapter_key,point.furthest_chapter_number,point.furthest_percent,bool(point.furthest_identity_inferred),point.furthest_content_version,value.resolve_furthest_chapter_key)):
            previous_key,previous_number,previous_percent=key,number,percent
            absent=kind=='furthest' and key is None and number==0 and not percent
            unresolved=not absent and (key is None or key not in by_key)
            being_archived=key in archive_keys
            inactive=not absent and key in by_key and by_key[key].archived and key not in mappings
            relocated=False
            if resolved_key is not None:
                if not (unresolved or being_archived) or resolved_key not in mappings or resolved_key in archive_keys or resolved_key==key:
                    raise HTTPException(422,'Resolve this saved position explicitly to a different retained, mapped local chapter.')
                relocated=being_archived
                key=resolved_key;inferred=True;unresolved=False;inactive=False;being_archived=False
                if relocated:percent=0;version=None;number=remote_by_key[mappings[key]]['chapter_number']
            if being_archived:blockers.append(dict(code=f'{kind}_anchor_archive_resolution_required',message=f'Choose a retained chapter for the saved {kind} position before archiving its original.'))
            if inactive:blockers.append(dict(code=f'{kind}_anchor_archived',message=f'Restore the preserved archived {kind} chapter explicitly, or change your reading position before reviewing this list.'))
            if unresolved:blockers.append(dict(code=f'{kind}_anchor_unresolved',message=f'Review the saved {kind} position at chapter {number} before changing addresses.'))
            anchors.append(dict(kind=kind,chapter_key=key,chapter_number=number,percent=percent or 0,identity_inferred=bool(inferred),resolved=not (unresolved or inactive or being_archived),content_version=version,relocated=relocated,previous_chapter_key=previous_key if relocated else None,previous_chapter_number=previous_number if relocated else None,previous_percent=previous_percent if relocated else None))
    if not point and (value.resolve_current_chapter_key or value.resolve_furthest_chapter_key):raise HTTPException(422,'There are no unresolved saved positions to map.')
    mapped_anchors={anchor['kind']:remote_by_key[mappings[anchor['chapter_key']]]['chapter_number'] for anchor in anchors if anchor['chapter_key'] in mappings}
    if 'current' in mapped_anchors and 'furthest' in mapped_anchors and mapped_anchors['current']>mapped_anchors['furthest']:
        blockers.append(dict(code='reading_order_changed',message='This order would place the current position after the furthest position. Review the reading session before changing chapter order.'))
    if _active(db,user_id,novel_id):blockers.append(dict(code='active_work',message='Wait for active downloads and generated work.'))
    details=[];unmapped=[];inferred_total=0
    inferred_counts=dict(db.query(ReadingHistory.chapter_key,func.count(ReadingHistory.id)).filter_by(user_id=user_id,novel_id=novel_id,identity_inferred=True).group_by(ReadingHistory.chapter_key).all())
    for item in local:
        target=remote_by_key.get(mappings.get(item.chapter_key))
        inferred_count=inferred_counts.get(item.chapter_key,0)
        inferred_count+=sum(1 for anchor in anchors if anchor['chapter_key']==item.chapter_key and anchor['identity_inferred'] and not anchor.get('relocated'))
        inferred_total+=inferred_count
        moving=target is not None and target['chapter_number']!=item.chapter_number
        if moving and inferred_count and item.chapter_key not in confirm:blockers.append(dict(code='inferred_anchor_confirmation_required',message=f'Review inferred saved positions for chapter {item.chapter_number} explicitly.'))
        archive_reason=_archive_reason(item,archive_context)
        detail=dict(can_archive=archive_reason is None,archive_blocked_reason=archive_reason[1] if archive_reason else None,archived=item.archived,chapter_key=item.chapter_key,metadata_chapter_key=target['chapter_key'] if target else None,title=item.title,
            from_number=item.chapter_number,to_number=target['chapter_number'] if target else None,
            decision='archive' if item.chapter_key in archive_keys else decisions.get(item.chapter_key,'explicit' if item.chapter_key in explicit else 'unlisted' if item.archived else 'needs_mapping'),
            requires_content_review=target is not None and (namespace_changed or (item.metadata_chapter_key is not None or item.chapter_key in explicit) and (item.metadata_manifest_key!=remote.manifest_key or item.metadata_chapter_key!=mappings.get(item.chapter_key))),
            inferred_anchor_count=inferred_count,candidates=[],candidates_truncated=False)
        if target is None and item.metadata_manifest_key==remote.manifest_key:
            choices=sorted(lineage.get(item.metadata_chapter_key,[]))
            detail['candidates']=[dict(metadata_chapter_key=key,chapter_number=remote_by_key[key]['chapter_number'],title=remote_by_key[key]['title'],identity_kind=remote_by_key[key]['identity_kind']) for key in choices[:20]]
            detail['candidates_truncated']=len(choices)>20
        details.append(detail)
        if target is None and not item.archived and item.chapter_key not in archive_keys:unmapped.append(detail)
    if unmapped:blockers.append(dict(code='unmapped_local_chapters',message='Map every preserved local chapter. This source snapshot does not authorize removals.'))
    used=set(mappings.values())
    new=[item for item in remote.items if item['chapter_key'] not in used]
    reused_archives={}
    retained_archives=[item for item in local if item.archived and item.chapter_key not in mappings]
    archived_source_keys={item.metadata_chapter_key for item in retained_archives if item.metadata_manifest_key==remote.manifest_key}
    archived_stable_ids={item.site_chapter_id for item in retained_archives if item.site_chapter_id is not None}
    for incoming in new:
        preserved=incoming['chapter_key'] in archived_source_keys or (namespace_ok and incoming['identity_kind']=='stable_source_id' and incoming['chapter_id'] in archived_stable_ids)
        if preserved:blockers.append(dict(code='archived_original_requires_mapping',message='An incoming source chapter matches a preserved archived original. Select that original explicitly instead of creating a second lifecycle.'))
    for item in new:details.append(dict(chapter_key=reused_archives.get(item['chapter_key']),metadata_chapter_key=item['chapter_key'],title=item['title'],from_number=None,
        to_number=item['chapter_number'],decision='new',requires_content_review=False,inferred_anchor_count=0,candidates=[],candidates_truncated=False))
    grouped_blockers={}
    for blocker in blockers:
        code=blocker['code']
        if code not in grouped_blockers:grouped_blockers[code]=dict(blocker,count=0)
        grouped_blockers[code]['count']+=1
    blockers=list(grouped_blockers.values())
    plan=dict(reviewed_manifest_epoch=header['manifest_epoch'],reviewed_manifest_revision=header['manifest_revision'],anchors=anchors,
        remote={key:getattr(remote,key,None) for key in ('manifest_key','revision','fingerprint','total','identity_kind','complete','source_complete','deletion_authoritative','source','source_capture_id','source_authority_kind','source_review_id','source_lineage_fingerprint')},
        source=source,blocked_reasons=blockers,archive_chapter_keys=sorted(archive_keys),mappings=mappings,confirm_inferred_anchors=sorted(confirm),
        uncertain_keys=[item['chapter_key'] for item in details if item['requires_content_review']],
        reused_archives={item['chapter_key']:reused_archives[item['chapter_key']] for item in new if item['chapter_key'] in reused_archives},namespace_changed=namespace_changed,
        counts=dict(newly_archived_chapters=len(archive_keys),source_chapters=remote.total,local_chapters=sum(not item.archived for item in local),archived_chapters=sum(item.archived for item in local),restored_chapters=sum(item.archived and item.chapter_key in mappings for item in local),mapped=len(mappings),new=len(new),
                    renumbered=sum(1 for item in details if item['from_number'] is not None and item['to_number'] is not None and item['from_number']!=item['to_number']),unmapped=len(unmapped),inferred_anchors=inferred_total))
    row=ChapterManifestReview(user_id=user_id,novel_id=novel_id,review_key=str(uuid4()),fingerprint=_private_digest(db,user_id,novel_id),
        plan=plan,expires_at=datetime.now(UTC).replace(tzinfo=None)+timedelta(hours=1))
    db.add(row);db.flush();ordinal=0
    for kind,items in (('items',details),('unmapped',unmapped),('remote',[dict(metadata_chapter_key=item['chapter_key'],chapter_number=item['chapter_number'],title=item['title'],identity_kind=item['identity_kind']) for item in remote.items])):
        for detail in items:
            db.add(ChapterManifestReviewItem(review_id=row.id,ordinal=ordinal,item_kind=kind,chapter_key=detail.get('chapter_key'),metadata_chapter_key=detail.get('metadata_chapter_key'),title=detail['title'],detail=detail));ordinal+=1
            if ordinal%500==0:db.flush()
    db.flush();result=_view(db,row);db.commit();return result


def _lock(db,user_id,novel_id,session_id=None):
    from config.database import Base
    sqlite_transaction(db,write=True)
    owner(db,user_id,novel_id,session_id,lock=True)
    for mapper in sorted(Base.registry.mappers,key=lambda m:m.local_table.name):
        model=mapper.class_
        if not all(hasattr(model,key) for key in ('novel_id','status','user_id')) or model.__tablename__.startswith('chapter_manifest_'):continue
        query=db.query(model.id).filter(model.novel_id==novel_id,model.user_id==user_id)
        if query.count()>200_000:raise HTTPException(422,'This review exceeds the 200,000-job limit.')
        for _ in query.order_by(model.id).with_for_update().yield_per(500):pass
    for _ in db.query(Chapter.id).execution_options(include_archived_chapters=True).filter(Chapter.novel_id==novel_id).order_by(Chapter.id).with_for_update().yield_per(500):pass
    manifest_state(db,novel_id,lock=True)
    db.expire_all()


def _receipt(db,user_id,operation_id,fingerprint):
    from app.models.chapter_manifest import ChapterManifestOperation
    row=db.query(ChapterManifestOperation).filter_by(user_id=user_id,operation_id=operation_id).first()
    if row:
        if row.fingerprint!=fingerprint:conflict('operation_reused','This operation ID belongs to a different chapter-list action.')
        return row.response
    return None


def _save_receipt(db,user_id,novel_id,operation_id,fingerprint,response):
    from app.models.chapter_manifest import ChapterManifestOperation
    db.add(ChapterManifestOperation(user_id=user_id,novel_id=novel_id,operation_id=operation_id,fingerprint=fingerprint,response=response))
    db.commit();return response


def _compact(row,state):
    return dict(review_id=row.id,revision=row.revision,status=row.status,novel_id=row.novel_id,**state_fields(state))


async def apply(db,user_id,novel_id,value,*,session_id=None):
    owner(db,user_id,novel_id,session_id)
    intent=_hash({'action':'apply','novel':novel_id,'token':value.review_token})
    replay=_receipt(db,user_id,value.operation_id,intent)
    if replay is not None:db.rollback();return replay
    try:token=jwt.decode(value.review_token,settings.SECRET_KEY,algorithms=[settings.ALGORITHM])
    except JWTError as exc:raise HTTPException(409,'This review expired. Build a new chapter preview.') from exc
    if token.get('purpose')!='chapter-topology-review-v1' or token.get('user')!=user_id:raise HTTPException(409,'Invalid chapter review')
    row=_review(db,user_id,novel_id,token.get('review'))
    if token.get('key')!=row.review_key or token.get('fingerprint')!=row.fingerprint:raise HTTPException(409,'Invalid chapter review')
    source=row.plan['source'];db.rollback()
    try:remote=await metadata_client.get_chapter_manifest(source['metadata_id'],force_refresh=True)
    except metadata_client.ChapterManifestError as exc:raise HTTPException(409,detail={'code':exc.category,'message':str(exc)}) from exc
    _lock(db,user_id,novel_id,session_id)
    replay=_receipt(db,user_id,value.operation_id,intent)
    if replay is not None:db.rollback();return replay
    row=_review(db,user_id,novel_id,token['review'])
    state=manifest_state(db,novel_id)
    if row.status!='preview' or row.expires_at<=datetime.now(UTC).replace(tzinfo=None):conflict('review_stale','Build a fresh chapter preview.')
    if row.plan['blocked_reasons'] or _active(db,user_id,novel_id):conflict('review_blocked','Resolve the review warnings and active work first.')
    if row.fingerprint!=_private_digest(db,user_id,novel_id):conflict('review_stale','Private reading state or originals changed after preview.')
    _,novel=owner(db,user_id,novel_id,session_id)
    if _source(novel)!=source or any(getattr(remote,key,None)!=row.plan['remote'].get(key) for key in ('manifest_key','revision','fingerprint','source_capture_id','source_authority_kind','source_review_id','source_lineage_fingerprint')):
        conflict('review_stale','The source chapter list changed after preview.')
    # All ancillary enqueue/publication paths must be enrolled before topology
    # is exposed. The parent integration explicitly completes this last gate.
    try:
        from app.services.chapter_topology_guards import require_complete_guards,TOPOLOGY_GUARDS_COMPLETE
        if not TOPOLOGY_GUARDS_COMPLETE:raise ImportError('Ancillary integration is not frozen')
    except ImportError as exc:
        raise HTTPException(503,detail={"code":"topology_guards_incomplete","message":"Chapter-list updates are awaiting complete derivative and evidence integration."}) from exc
    require_complete_guards(db,user_id,novel_id)
    chapters=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(novel_id=novel_id).all()
    by_key={chapter.chapter_key:chapter for chapter in chapters}
    remote_by_key={item['chapter_key']:item for item in remote.items}
    mapping=row.plan['mappings']
    archive_keys=_archive_selection(row.plan.get('archive_chapter_keys',[]),by_key,remote,state,row.plan.get('namespace_changed',False))
    if set(mapping)&archive_keys or not {chapter.chapter_key for chapter in chapters if not chapter.archived}<=set(mapping)|archive_keys or not set(mapping)<=set(by_key):conflict('review_stale','Every preserved chapter needs an explicit or proven identity mapping.')
    point_before=_point(db,user_id,novel_id)
    from app.services.reading_run_service import PROGRESS_FIELDS
    point_snapshot={key:getattr(point_before,key) for key in (*PROGRESS_FIELDS,'chapter_id')} if point_before is not None else None
    proof_before=[]
    for key in row.plan.get('uncertain_keys',[]):
        proof_before.extend({'table':'receipt','id':r.id,'requires_review':r.requires_review} for r in db.query(ChapterReadReceipt).filter_by(user_id=user_id,chapter_key=key))
        proof_before.extend({'table':'history','id':r.id,'verified_percent':r.verified_percent,'verified_content_version':r.verified_content_version} for r in db.query(ReadingHistory).filter_by(user_id=user_id,novel_id=novel_id,chapter_key=key))
    row.before_state={'novel_source':_source(novel),'reactivated':[],'progress':point_snapshot,'proof':proof_before,'chapters':[{key:getattr(chapter,key) for key in ('id','chapter_key','chapter_number','title','site_chapter_id','source_url','metadata_manifest_key','metadata_chapter_key','category','word_count','archived')}|{'archived_at':chapter.archived_at.isoformat() if chapter.archived_at else None} for chapter in chapters],
        'metadata':{key:getattr(state,key) for key in ('metadata_source','metadata_manifest_key','metadata_revision','metadata_fingerprint')},
        'created_chapter_keys':[]}
    changed=[]
    for key,target_key in mapping.items():
        chapter=by_key[key];target=remote_by_key[target_key]
        if len(target.get('url') or '')>500:raise HTTPException(422,'A chapter source URL exceeds the supported 500-character limit; no changes were made.')
        changed.append(chapter)
    # Partial unique indexes allow swaps without temporary numeric labels or
    # permanently archiving originals. Every mutation remains one transaction.
    for key in archive_keys:
        by_key[key].archived=True;by_key[key].archived_at=datetime.now(UTC).replace(tzinfo=None)
    for chapter in changed:chapter.archived=True
    db.flush()
    from app.services.chapter_version_service import retain_current
    for key,target_key in mapping.items():
        chapter=by_key[key];target=remote_by_key[target_key]
        retain_current(db,chapter,reason='chapter_list_review')
        chapter.chapter_number=target['chapter_number'];chapter.metadata_manifest_key=remote.manifest_key
        chapter.metadata_chapter_key=target_key;chapter.site_chapter_id=target['chapter_id'];chapter.source_url=target['url'];chapter.category=target['category']
    db.flush()
    for chapter in changed:chapter.archived=False;chapter.archived_at=None
    db.flush()
    used=set(mapping.values())
    revivable_current=_revivable_archives(db,user_id,novel_id,remote.manifest_key)
    created_ordinal=db.query(func.max(ChapterManifestReviewItem.ordinal)).filter_by(review_id=row.id).scalar() or 0
    activated=[]
    for item in remote.items:
        if item['chapter_key'] in used:continue
        if len(item.get('url') or '')>500:raise HTTPException(422,'A chapter source URL exceeds the supported 500-character limit; no changes were made.')
        reused_key=row.plan.get('reused_archives',{}).get(item['chapter_key'])
        if reused_key:
            if revivable_current.get(item['chapter_key'])!=reused_key:
                conflict('review_stale','A preserved placeholder acquired reading state. Build a fresh review.')
            chapter=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(novel_id=novel_id,chapter_key=reused_key).one()
            fields=('chapter_key','chapter_number','title','site_chapter_id','source_url','metadata_manifest_key','metadata_chapter_key','category','word_count')
            row.before_state['reactivated'].append({**{key:getattr(chapter,key) for key in fields},'archived_at':chapter.archived_at.isoformat() if chapter.archived_at else None})
            chapter.archived=False;chapter.archived_at=None
            for field,field_value in dict(chapter_number=item['chapter_number'],title=item['title'],site_chapter_id=item['chapter_id'],source_url=item['url'],category=item['category'],word_count=item['word_count']).items():setattr(chapter,field,field_value)
        else:
            chapter=Chapter(novel_id=novel_id,chapter_number=item['chapter_number'],title=item['title'],site_chapter_id=item['chapter_id'],source_url=item['url'],
                category=item['category'],word_count=item['word_count'],metadata_manifest_key=remote.manifest_key,metadata_chapter_key=item['chapter_key'])
            db.add(chapter)
        activated.append((chapter,item))
    db.flush()
    hydrate_chapter_keys(db,[chapter for chapter,_ in activated])
    for chapter,item in activated:
        row.before_state['created_chapter_keys'].append(chapter.chapter_key)
        created_ordinal+=1
        db.add(ChapterManifestReviewItem(review_id=row.id,ordinal=created_ordinal,item_kind='created',chapter_key=chapter.chapter_key,metadata_chapter_key=item['chapter_key'],title=chapter.title,detail={}))
    from sqlalchemy.orm.attributes import flag_modified
    flag_modified(row,'before_state')
    if len(remote.source.get('source_url') or '')>500 or len(remote.source.get('site') or '')>255:
        raise HTTPException(422,'The reviewed source namespace exceeds local storage limits; no chapter list was changed.')
    novel.site=remote.source.get('site');novel.novel_site=remote.source.get('site')
    novel.story_id=remote.source.get('story_id');novel.site_story_id=remote.source.get('story_id');novel.source_url=remote.source.get('source_url')
    state.ao3_material=state.ao3_material or ao3_source(remote.source)
    state.metadata_source=dict(remote.source);state.metadata_manifest_key=remote.manifest_key;state.metadata_revision=remote.revision;state.metadata_fingerprint=remote.fingerprint;state.identity_required=True
    db.flush();db.refresh(state)
    _move_current_progress(db,user_id,novel_id,row.plan,by_key,state)
    row.status='applied';row.applied_at=datetime.now(UTC).replace(tzinfo=None);row.revision+=1
    db.flush();row.after_fingerprint=_private_digest(db,user_id,novel_id)
    return _save_receipt(db,user_id,novel_id,value.operation_id,intent,_compact(row,state))


def _move_current_progress(db,user_id,novel_id,plan,by_key,state):
    from app.services.reading_run_service import current_run,snapshot_progress
    point=_point(db,user_id,novel_id)
    # Uncertain explicit source associations retain originals but never grant
    # new read evidence. Existing historical max/date values remain untouched.
    uncertain={key for key,target in plan['mappings'].items() if key in plan.get('uncertain_keys',[])}
    for key in uncertain:
        db.query(ChapterReadReceipt).filter_by(user_id=user_id,chapter_key=key).update({'requires_review':True},synchronize_session=False)
        db.query(ReadingHistory).filter_by(user_id=user_id,novel_id=novel_id,chapter_key=key).update({'verified_percent':0,'verified_content_version':None},synchronize_session=False)
        if point is not None and point.chapter_key==key:point.source_content_version=None
        if point is not None and point.furthest_chapter_key==key:point.furthest_content_version=None
    if point is None:return
    if point.id is None:db.add(point);db.flush()
    for anchor in plan['anchors']:
        key=anchor['chapter_key']
        if key is None:continue
        chapter=by_key[key]
        if anchor['kind']=='current':
            point.chapter_id=chapter.id;point.chapter_key=key;point.chapter_number=chapter.chapter_number
            point.current_identity_inferred=anchor['identity_inferred']
            if anchor.get('relocated'):
                point.percent=0;point.position=0;point.text_offset=0;point.source_content_version=None
                for field in ('block_id','text_quote','quote_prefix','quote_suffix','locator_content_version','locator_variant'):setattr(point,field,None)
        else:
            point.furthest_chapter_key=key;point.furthest_chapter_number=chapter.chapter_number
            point.furthest_identity_inferred=int(anchor['identity_inferred'])
            if anchor.get('relocated'):point.furthest_percent=0;point.furthest_content_version=None
    point.manifest_epoch=state.manifest_epoch;point.manifest_revision=str(state.revision);point.revision=int(point.revision or 0)+1
    run=current_run(db,user_id,novel_id,point)
    if run:run.progress_snapshot=snapshot_progress(run,point)


def undo(db,user_id,novel_id,review_id,value,*,session_id=None):
    _lock(db,user_id,novel_id,session_id)
    intent=_hash({'action':'undo','novel':novel_id,'review':review_id,**value.model_dump(exclude={'operation_id'})})
    replay=_receipt(db,user_id,value.operation_id,intent)
    if replay is not None:db.rollback();return replay
    row=_review(db,user_id,novel_id,review_id);state=manifest_state(db,novel_id)
    if value.expected_manifest_epoch!=state.manifest_epoch or value.expected_manifest_revision!=str(state.revision):conflict('chapter_manifest_changed','Refresh the chapter list before reviewing undo.',state_fields(state))
    if row.status!='applied' or value.expected_revision!=row.revision:conflict('review_stale','This review changed after the undo dialog opened.')
    if _active(db,user_id,novel_id) or row.after_fingerprint!=_private_digest(db,user_id,novel_id):conflict('undo_changed','Reading state, originals or generated work changed after this chapter-list update. Undo cannot discard those changes.')
    try:
        from app.services.chapter_topology_guards import require_complete_guards,TOPOLOGY_GUARDS_COMPLETE
        if not TOPOLOGY_GUARDS_COMPLETE:raise ImportError('Ancillary integration is not frozen')
    except ImportError as exc:
        raise HTTPException(503,detail={'code':'topology_guards_incomplete','message':'Chapter-list undo is awaiting complete derivative and evidence integration.'}) from exc
    require_complete_guards(db,user_id,novel_id)
    before=row.before_state
    chapters=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(novel_id=novel_id).all()
    by_key={chapter.chapter_key:chapter for chapter in chapters}
    originals={chapter['chapter_key']:chapter for chapter in before['chapters']}
    # New empty additions are archived, retaining their lifecycle for old URLs.
    for chapter in chapters:chapter.archived=True
    db.flush()
    for key,data in originals.items():
        chapter=by_key[key]
        for field,old in data.items():
            if field not in ('id','chapter_key','archived','archived_at'):setattr(chapter,field,old)
    db.flush()
    for key,data in originals.items():
        by_key[key].archived=data['archived'];by_key[key].archived_at=datetime.fromisoformat(data['archived_at']) if data['archived_at'] else None
    for key in before['created_chapter_keys']:by_key[key].archived_at=datetime.now(UTC).replace(tzinfo=None)
    for data in before.get('reactivated',[]):
        chapter=by_key[data['chapter_key']]
        for field,old in data.items():
            if field=='chapter_key':continue
            setattr(chapter,field,datetime.fromisoformat(old) if field=='archived_at' and old else old)
    db.flush()
    _,novel=owner(db,user_id,novel_id,session_id)
    for field,old in before['novel_source'].items():
        if field not in ('library_id','metadata_id','url'):setattr(novel,field,old)
    for field,old in before['metadata'].items():setattr(state,field,old)
    db.flush();db.refresh(state)
    point=db.query(ReadingProgress).filter_by(user_id=user_id,novel_id=novel_id).first()
    if before['progress'] is not None:
        if point is None:conflict('undo_changed','The saved position disappeared after this update.')
        revision=point.revision
        for field,old in before['progress'].items():
            if field not in ('revision','manifest_epoch','manifest_revision'):setattr(point,field,old)
        point.revision=int(revision or 0)+1;point.manifest_epoch=state.manifest_epoch;point.manifest_revision=str(state.revision)
        from app.services.reading_run_service import current_run,snapshot_progress
        run=current_run(db,user_id,novel_id,point)
        if run:run.progress_snapshot=snapshot_progress(run,point)
    for item in before['proof']:
        model=ChapterReadReceipt if item['table']=='receipt' else ReadingHistory
        target=db.query(model).filter_by(id=item['id'],user_id=user_id).first()
        if target is None:conflict('undo_changed','Historical read evidence changed after this update.')
        for field,old in item.items():
            if field not in ('table','id'):setattr(target,field,old)
    row.status='undone';row.undone_at=datetime.now(UTC).replace(tzinfo=None);row.revision+=1
    db.flush()
    return _save_receipt(db,user_id,novel_id,value.operation_id,intent,_compact(row,state))


def keyed_content(db,user_id,novel_id,chapter_key,*,session_id=None,content_version=None):
    from app.services.chapter_document import from_text
    from app.models.chapter_version import ChapterVersion
    sqlite_transaction(db);owner(db,user_id,novel_id,session_id)
    chapter=db.query(Chapter).execution_options(include_archived_chapters=True).filter_by(novel_id=novel_id,chapter_key=chapter_key).first()
    if chapter is None:raise HTTPException(404,'Chapter identity not found')
    current=chapter.document or from_text(chapter.content or '')
    value=chapter;document=current
    if content_version is not None and content_version!=current['content_version']:
        value=db.query(ChapterVersion).filter_by(chapter_id=chapter.id,chapter_key=chapter_key,content_version=content_version).first()
        if value is None:raise HTTPException(404,'This saved chapter version is unavailable')
        document=value.document
    if not document.get('blocks'):raise HTTPException(409,'Chapter content is not downloaded')
    result=dict(chapter_key=chapter_key,**state_fields(manifest_state(db,novel_id)),id=chapter.id,novel_id=novel_id,chapter_number=chapter.chapter_number,
        title=value.title or f'Chapter {chapter.chapter_number}',content=document['plain_text'],document=document,source_url=value.source_url,
        source_version=document['content_version'],current_content_version=current['content_version'],archived=chapter.archived)
    db.rollback();return result


def ingest_metadata_snapshot(db,novel,snapshot):
    """Atomically stage an initial manifest or proven append, never a reorder.

    The caller must revalidate owner/session/source after remote I/O. This
    synchronous helper locks the owned story and chapters, validates the entire
    snapshot before its first mutation, and leaves commit to the caller.
    """
    from app.services.metadata_client import ChapterManifestSnapshot
    if not isinstance(snapshot,ChapterManifestSnapshot) or snapshot.novel_id!=novel.metadata_id or not snapshot.complete:
        raise HTTPException(422,'Use a complete, validated metadata manifest snapshot for this story.')
    user_id=db.query(Library.user_id).filter(Library.id==novel.library_id).scalar()
    if user_id is None:raise HTTPException(404,'Story not found')
    sqlite_transaction(db,write=True)
    db.query(User.id).filter_by(id=user_id).with_for_update().first()
    original=db.query(Novel.id,Novel.metadata_id,Novel.site,Novel.novel_site,Novel.site_story_id,Novel.story_id,Novel.source_url).join(
        Library,Library.id==Novel.library_id).filter(Novel.id==novel.id,Library.user_id==user_id).with_for_update(of=Novel).first()
    if original is None:raise HTTPException(404,'Story not found')
    if original.metadata_id not in (None,snapshot.novel_id) or not known_source_matches(original,snapshot.source):
        conflict('chapter_review_required','The persisted private source differs from this snapshot. Review it before replacing source facts.')
    # The source caller may have staged authorized display metadata. Flush it
    # only AFTER authority locks, before populate_existing refreshes that row.
    db.flush()
    _,fresh=owner(db,user_id,novel.id,lock=True)
    if fresh.metadata_id!=snapshot.novel_id:conflict('chapter_review_required','The linked source changed. Review its chapter list.')
    query=db.query(Chapter).execution_options(include_archived_chapters=True).filter(Chapter.novel_id==fresh.id)
    if query.count()>MAX_CHAPTERS:raise HTTPException(422,'This story exceeds the 200,000-chapter ingestion limit.')
    local=query.order_by(Chapter.id).with_for_update().all()
    state=manifest_state(db,fresh.id,lock=True)
    if not known_source_matches(fresh,snapshot.source):
        conflict('chapter_review_required','The captured source namespace differs from this private story. Review it before binding source chapters.')
    if state.metadata_source is not None and state.metadata_source!=snapshot.source:
        conflict('chapter_review_required','The source work namespace changed. Review it before accepting any source chapter binding.')
    if state.metadata_manifest_key not in (None,snapshot.manifest_key):conflict('chapter_review_required','The metadata work has a different lifecycle. Review before accepting its chapter list.')
    remote_by_key={item['chapter_key']:item for item in snapshot.items}
    stable={}
    for item in snapshot.items:
        if len(item.get('url') or '')>500 or len(item.get('title') or '')>255:
            raise HTTPException(422,'A source chapter title or URL exceeds local storage limits; no chapter list was changed.')
        if item['identity_kind']=='stable_source_id':stable.setdefault(item['chapter_id'],[]).append(item)
    namespace_ok=snapshot.source.get('site') in (fresh.site,fresh.novel_site) and snapshot.source.get('story_id') in (fresh.site_story_id,fresh.story_id) and snapshot.source.get('story_id') is not None
    source_counts={}
    for chapter in local:source_counts[chapter.site_chapter_id]=source_counts.get(chapter.site_chapter_id,0)+1
    bindings={};used=set()
    for chapter in local:
        if chapter.archived:conflict('chapter_review_required','This story has preserved archived originals. Review additions against its explicit chapter list.')
        target=None
        if chapter.metadata_manifest_key==snapshot.manifest_key:
            target=remote_by_key.get(chapter.metadata_chapter_key)
        elif chapter.metadata_manifest_key is None and chapter.metadata_chapter_key is None and namespace_ok and source_counts[chapter.site_chapter_id]==1:
            candidates=stable.get(chapter.site_chapter_id,[])
            if len(candidates)==1:target=candidates[0]
        if target is None or target['chapter_key'] in used or target['chapter_number']!=chapter.chapter_number:
            conflict('chapter_review_required','Existing chapters changed identity, position or source membership. Build a reviewed chapter-list update; originals were preserved.')
        if chapter.site_chapter_id!=target['chapter_id'] or chapter.source_url not in (None,target['url']) or chapter.category!=target['category']:
            conflict('chapter_review_required','Existing source facts changed. Review the chapter list before refreshing its bindings.')
        bindings[chapter.chapter_key]=target;used.add(target['chapter_key'])
    # Appending into the middle also changes reading order and requires review.
    existing_max=max((chapter.chapter_number for chapter in local),default=None)
    additions=[item for item in snapshot.items if item['chapter_key'] not in used]
    if existing_max is not None and any(item['chapter_number']<=existing_max for item in additions):
        conflict('chapter_review_required','The source inserted chapters into the existing reading order. Review their placement first.')
    for chapter in local:
        target=bindings[chapter.chapter_key]
        chapter.metadata_manifest_key=snapshot.manifest_key;chapter.metadata_chapter_key=target['chapter_key']
    created=[]
    for item in additions:
        chapter=Chapter(novel_id=fresh.id,chapter_number=item['chapter_number'],title=item['title'],site_chapter_id=item['chapter_id'],source_url=item['url'],category=item['category'],word_count=item['word_count'],
            metadata_manifest_key=snapshot.manifest_key,metadata_chapter_key=item['chapter_key'])
        db.add(chapter);created.append(chapter)
    state.ao3_material=state.ao3_material or ao3_source(snapshot.source)
    state.metadata_source=dict(snapshot.source);state.metadata_manifest_key=snapshot.manifest_key;state.metadata_revision=snapshot.revision;state.metadata_fingerprint=snapshot.fingerprint
    db.flush()
    hydrate_chapter_keys(db,created)
    db.refresh(state)
    return created


def _revivable_archives(db,user_id,novel_id,manifest_key):
    """Only pristine additions created then undone by this review protocol.

    A retained original, note, receipt, run locator or derivative is never
    treated as an empty placeholder merely because its current text is empty.
    """
    from config.database import Base
    from sqlalchemy import or_
    from app.models.reading_run import ReadingRun
    rows=db.query(Chapter.id,Chapter.chapter_key,Chapter.metadata_chapter_key).execution_options(include_archived_chapters=True).join(
        ChapterManifestReviewItem,ChapterManifestReviewItem.chapter_key==Chapter.chapter_key).join(
        ChapterManifestReview,ChapterManifestReview.id==ChapterManifestReviewItem.review_id).filter(
            Chapter.novel_id==novel_id,Chapter.archived.is_(True),Chapter.metadata_manifest_key==manifest_key,
            or_(Chapter.content.is_(None),Chapter.content==''),Chapter.document.is_(None),
            ChapterManifestReviewItem.item_kind=='created',ChapterManifestReview.user_id==user_id,
            ChapterManifestReview.novel_id==novel_id,ChapterManifestReview.status=='undone').distinct().limit(MAX_CHAPTERS+1).all()
    if len(rows)>MAX_CHAPTERS:raise HTTPException(422,'This story exceeds the archived-placeholder review limit.')
    by_id={row.id:row.chapter_key for row in rows};keys=set(by_id.values());blocked=set()
    for mapper in sorted(Base.registry.mappers,key=lambda m:m.local_table.name):
        model=mapper.class_
        if model is Chapter or model.__tablename__.startswith('chapter_manifest_'):continue
        if hasattr(model,'chapter_id'):
            ids=list(by_id)
            for start in range(0,len(ids),500):
                for chapter_id, in db.query(model.chapter_id).filter(model.chapter_id.in_(ids[start:start+500])).distinct():blocked.add(by_id[chapter_id])
        if hasattr(model,'chapter_key'):
            values=list(keys)
            for start in range(0,len(values),500):
                blocked.update(key for key, in db.query(model.chapter_key).filter(model.chapter_key.in_(values[start:start+500])).distinct())
        if hasattr(model,'furthest_chapter_key'):
            values=list(keys)
            for start in range(0,len(values),500):
                blocked.update(key for key, in db.query(model.furthest_chapter_key).filter(model.furthest_chapter_key.in_(values[start:start+500])).distinct())
    values=list(keys)
    for start in range(0,len(values),500):
        subset=values[start:start+500]
        snapshots=db.query(ReadingRun.progress_snapshot['chapter_key'].as_string(),ReadingRun.progress_snapshot['furthest_chapter_key'].as_string()).filter(
            ReadingRun.user_id==user_id,ReadingRun.novel_id==novel_id,or_(ReadingRun.progress_snapshot['chapter_key'].as_string().in_(subset),ReadingRun.progress_snapshot['furthest_chapter_key'].as_string().in_(subset)))
        for current,furthest in snapshots:blocked.update(key for key in (current,furthest) if key in keys)
    candidates={}
    for row in rows:
        if row.chapter_key not in blocked:candidates.setdefault(row.metadata_chapter_key,[]).append(row.chapter_key)
    # Ambiguous prior placeholders require a new explicit review, never pick
    # a database row just because it happens to sort first.
    return {remote:keys[0] for remote,keys in candidates.items() if len(keys)==1}


def hydrate_chapter_keys(db,chapters):
    """SQLite AFTER INSERT defaults are read once per bounded ID batch.

    Never mint an application UUID or issue one refresh per chapter. Mark the
    actual database value committed so this read cannot become an UPDATE that
    the immutable-key trigger correctly rejects.
    """
    from sqlalchemy.orm.attributes import set_committed_value
    by_id={chapter.id:chapter for chapter in chapters}
    ids=list(by_id)
    for start in range(0,len(ids),500):
        rows=db.query(Chapter.id,Chapter.chapter_key).execution_options(include_archived_chapters=True).filter(Chapter.id.in_(ids[start:start+500])).all()
        for id,key in rows:
            if key is None:raise HTTPException(503,'The chapter identity migration is incomplete')
            set_committed_value(by_id[id],'chapter_key',key)
