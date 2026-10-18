"""Authenticated metadata events wake a fresh identity-bound manifest sync.

Event ordinals never authorize local mutation. A late event may wake a newer
proven append; only newly created local rows produce notices/downloads.
"""
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from app.models import Chapter, Library, Novel, User
from app.models.chapter import ContentStatus
from app.models.download_job import ChapterDownloadJob
from app.models.metadata_webhook_delivery import MetadataWebhookDelivery
from app.models.novel_personal import NovelPersonalData
from app.models.update_event import NovelUpdateEvent
from app.services import metadata_client
from app.services.chapter_identity_service import sqlite_transaction
from app.services.chapter_manifest_service import ingest_metadata_snapshot
from app.services.source_refresh_guard import capture_source,revalidate_source


def delivery_key(event):
    return event.delivery_id or f'{event.source_id}:{event.job_id}:{event.event}'


def normalized_proof(event):
    from pydantic import ValidationError
    from app.schemas.metadata_event_proof import MetadataEventManifestProof
    proof=getattr(event,'manifest_proof',None)
    if proof is None:return None
    if hasattr(proof,'model_dump'):proof=proof.model_dump()
    try:return MetadataEventManifestProof.model_validate(proof).model_dump()
    except ValidationError as exc:
        raise HTTPException(422,detail={'code':'invalid_event_proof','message':'Supply a complete manifest event proof with at most 1,000 canonical chapter identities.'}) from exc


def group_key(event):
    import hashlib
    import json
    proof=normalized_proof(event)
    if not isinstance(proof,dict) or not all(isinstance(proof.get(field),str) for field in ('manifest_key','revision')):return None
    value=[event.source_id,str(event.job_id),event.event,proof['manifest_key'],proof['revision'],proof['fingerprint'],proof['source']]
    # Include the entire immutable header: a malformed replay cannot borrow a
    # committed group's bypass of network/proof validation.
    return 'manifest-wakeup:'+hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def proof_problem(event,snapshot):
    proof=normalized_proof(event)
    if not proof:return None  # Legacy event is only a wake-up, never evidence.
    if not isinstance(proof,dict):return 'invalid_event_proof'
    import re
    if (proof.get('protocol')!=1 or type(proof.get('protocol')) is not int
            or any(not isinstance(proof.get(field),str) or re.fullmatch('[a-f0-9]{64}',proof[field]) is None
                   for field in ('revision','fingerprint'))):return 'invalid_event_proof'
    if proof.get('manifest_key')!=snapshot.manifest_key or proof.get('source')!=snapshot.source:
        return 'source_lifecycle_changed'
    if proof.get('revision')==snapshot.revision and proof.get('fingerprint')!=snapshot.fingerprint:
        return 'event_fingerprint_changed'
    selected=proof.get('chapters')
    if not isinstance(selected,list) or len(selected)>1000:return 'invalid_event_proof'
    current={item['chapter_key']:item['chapter_number'] for item in snapshot.items}
    keys=set()
    for item in selected:
        if (not isinstance(item,dict) or set(item)!={'chapter_key','chapter_number'}
                or not isinstance(item['chapter_key'],str) or type(item['chapter_number']) is not int
                or item['chapter_key'] in keys or current.get(item['chapter_key'])!=item['chapter_number']):
            return 'referenced_chapter_changed'
        keys.add(item['chapter_key'])
    return None


def claim(db,event,*,key=None):
    try:
        with db.begin_nested():
            db.add(MetadataWebhookDelivery(delivery_key=key or delivery_key(event),source_job_id=str(event.job_id),
                source_id=event.source_id,event_type=event.event));db.flush()
    except IntegrityError:return False
    return True


def review(db,novel,event,code):
    db.add(NovelUpdateEvent(user_id=novel.library.user_id,novel_id=novel.id,
        event_type='source_manifest_review_required',message='The source chapter list needs review before automatic updates can continue.',
        notification_visible=False,details={'code':code,'delivery_id':delivery_key(event),'source_job_id':str(event.job_id)}))


def queue(db,novel,follow,created):
    from app.services.library_organization_service import followed_categories_of,DEFAULT_KEEP_AHEAD,MAX_KEEP_AHEAD,MIN_KEEP_AHEAD
    from app.services.reading_order import last_finished_number
    active={value for value, in db.query(ChapterDownloadJob.chapter_id).filter(
        ChapterDownloadJob.user_id==follow.user_id,ChapterDownloadJob.novel_id==novel.id,
        ChapterDownloadJob.status.in_({'queued','processing','retry_wait'}))}
    count=1 if follow.download_policy=='next_chapter' else max(follow.download_count or 0,0) if follow.download_policy=='next_n' else 0
    selected=sorted(created,key=lambda c:c.chapter_number)[:min(count,200_000)]
    personal=db.query(NovelPersonalData).filter_by(user_id=follow.user_id,novel_id=novel.id).first()
    if personal and personal.auto_download:
        query=db.query(Chapter).filter(Chapter.novel_id==novel.id,Chapter.category.in_(followed_categories_of(personal)),Chapter.content_status!=ContentStatus.PRESENT)
        position=last_finished_number(db,follow.user_id,novel.id)
        if position is not None:query=query.filter(Chapter.chapter_number>position)
        ahead=min(max(personal.keep_ahead or DEFAULT_KEEP_AHEAD,MIN_KEEP_AHEAD),MAX_KEEP_AHEAD)
        selected+=query.order_by(Chapter.chapter_number,Chapter.id).limit(min(ahead,50)).all()
    added=0
    for chapter in selected:
        if chapter.id in active or chapter.content_status==ContentStatus.PRESENT:continue
        # Model insertion captures the exact remote/local lifecycle in this TX.
        db.add(ChapterDownloadJob(user_id=follow.user_id,library_id=novel.library_id,novel_id=novel.id,chapter_id=chapter.id))
        active.add(chapter.id);added+=1
    db.flush()
    return added


async def receive_completed(db,event):
    """Caller authenticates the internal webhook secret; caller must await us.

    No receipt or row lock crosses network I/O. A retryable manifest failure
    leaves no receipt. Permanent incompatible changes get a durable private
    review notice, preserving all original chapters and recordings.
    """
    normalized_proof(event)
    key=delivery_key(event)
    if db.query(MetadataWebhookDelivery.id).filter_by(delivery_key=key).first():
        db.rollback();return {'accepted':True,'created_events':0,'queued_downloads':0,'state':'duplicate'}
    group=group_key(event)
    if group and db.query(MetadataWebhookDelivery.id).filter_by(delivery_key=group).first():
        if claim(db,event):db.commit()
        else:db.rollback()
        return {'accepted':True,'created_events':0,'queued_downloads':0,'state':'duplicate_group'}
    candidates=db.query(Novel.id,Novel.library_id,Novel.metadata_id,Novel.url,Novel.source_url,Novel.site,Novel.novel_site,Novel.story_id,Novel.site_story_id,Library.user_id.label('owner_id')).join(Library,Library.id==Novel.library_id).join(User,User.id==Library.user_id).filter(
        Novel.metadata_id==event.metadata_novel_id,User.is_disabled.is_(False)).order_by(User.id,Novel.id).limit(10_001).all()
    if len(candidates)>10_000:
        db.rollback();raise HTTPException(503,'This metadata event exceeds the owned-copy transaction capacity; retry with a partitioned event.')
    authorities=[]
    for novel in candidates:
        authorities.append(capture_source(db,novel.owner_id,novel))
    db.rollback()
    snapshot=None;problem=None
    try:
        # Explicit guarded-content capability avoids accepting an older peer
        # whose numeric fetch endpoint silently ignores identity parameters.
        caps=await metadata_client._manifest_request('/chapters/manifest-capabilities')
        if not isinstance(caps,dict) or caps.get('content_identity') is not True or not isinstance(caps.get('protocols'),list) or 1 not in caps['protocols']:
            problem='metadata_upgrade_required'
        else:
            snapshot=await metadata_client.get_chapter_manifest(event.metadata_novel_id,force_refresh=True)
            problem=proof_problem(event,snapshot)
    except metadata_client.ChapterManifestError as exc:
        db.rollback()
        if exc.retryable:raise HTTPException(503,detail={'code':exc.category,'message':str(exc)}) from exc
        problem=exc.category
    sqlite_transaction(db,write=True)
    # Lock every account first, then its stories: same order as manual sync.
    user_ids=sorted({authority[0] for authority in authorities})
    for user_id in user_ids:db.query(User).filter_by(id=user_id).populate_existing().with_for_update().first()
    if not claim(db,event):
        db.rollback();return {'accepted':True,'created_events':0,'queued_downloads':0,'state':'duplicate'}
    if group and db.query(MetadataWebhookDelivery.id).filter_by(delivery_key=group).first():
        db.commit();return {'accepted':True,'created_events':0,'queued_downloads':0,'state':'duplicate_group'}
    from app.routers.novel import get_existing_follow,create_update_event
    created_events=queued_downloads=reviews=unhandled=0
    for authority in authorities:
        one_event=one_queue=0
        try:
            with db.begin_nested():
                novel=revalidate_source(db,authority,allow_metadata_advance=True)
                follow=get_existing_follow(db,authority[0],novel)
                if not follow or follow.state in {'on_hold','completed','dropped','ignored'}:continue
                if problem:
                    review(db,novel,event,problem);reviews+=1;continue
                from urllib.parse import urlsplit,urlunsplit
                def normalized(value):
                    parts=urlsplit(value or '')
                    return urlunsplit((parts.scheme.lower(),parts.netloc.lower(),parts.path.rstrip('/'),parts.query,''))
                if (snapshot.source.get('site') not in (novel.site,novel.novel_site)
                        or (any(value not in (None,0) for value in (novel.site_story_id,novel.story_id)) and snapshot.source.get('story_id') not in (novel.site_story_id,novel.story_id))
                        or not snapshot.source.get('source_url')
                        or normalized(snapshot.source['source_url'])!=normalized(novel.source_url or novel.url)):
                    raise HTTPException(409,detail={'code':'source_identity_changed'})
                created=ingest_metadata_snapshot(db,novel,snapshot)
                if not created:continue
                update=create_update_event(db,novel,event_type='new_chapters',chapter_numbers=[row.chapter_number for row in created],
                    message=f'{len(created)} new chapter(s) available')
                if update:
                    update.details={**(update.details or {}),'source_job_id':str(event.job_id),'source_id':event.source_id,
                        'site':event.site,'manifest_key':snapshot.manifest_key,'manifest_revision':snapshot.revision,
                        'chapter_keys':[row.chapter_key for row in created]}
                    one_event=1
                one_queue=queue(db,novel,follow,created)
            created_events+=one_event;queued_downloads+=one_queue
        except HTTPException as exc:
            if exc.status_code not in {401,404,409,422}:raise
            if exc.status_code in {401,404}:continue  # Deleted account/copy is not a retry target.
            try:
                # The row ID may now name a different source/lifecycle. Never
                # attach old-source review details to that replacement copy.
                novel=revalidate_source(db,authority,allow_metadata_advance=True)
            except HTTPException as current:
                if current.status_code in {401,404,409}:
                    unhandled+=1
                    continue
                raise
            detail=exc.detail if isinstance(exc.detail,dict) else {}
            review(db,novel,event,detail.get('code','chapter_review_required'));reviews+=1
    if group and not reviews and not unhandled:claim(db,event,key=group)
    db.commit()
    return {'accepted':True,'created_events':created_events,'queued_downloads':queued_downloads,
        'state':'review_required' if reviews else 'source_changed' if unhandled else 'applied','review_required':reviews}
