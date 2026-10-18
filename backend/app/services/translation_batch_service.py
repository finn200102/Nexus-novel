"""Review and enqueue exact saved chapter selections without invoking providers."""
from datetime import datetime, timedelta, timezone
from copy import deepcopy
import hashlib
import json

from fastapi import HTTPException
from jose import JWTError, jwt
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import load_only

from app.models import Chapter
from app.models.translation import ReaderProvider, TranslationJob
from app.models.story_processing_permission import StoryProcessingPermission
from app.services import processing_permissions
from app.services.chapter_document import from_text
from app.services.reader_provider import cost, validate_destination, MAX_OUTPUT_TOKENS
from app.services.translation_service import glossary_for, PIPELINE_VERSION, variant_fingerprint, compatible_completed
from app.services.job_lease import utcnow
from app.services.translation_export_service import owned_story, byte_length
from config.settings import settings

MAX_BYTES = 20 * 1024**2
MAX_BLOCKS = 20_000
REVIEW_MINUTES = 15


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def chapter_list(db, user_id, novel_id, offset, limit):
    owned_story(db, user_id, novel_id)
    query = db.query(Chapter).filter_by(novel_id=novel_id)
    total = query.count()
    from app.services.chapter_identity_service import manifest_state,state_fields
    manifest=state_fields(manifest_state(db,novel_id))
    rows = query.with_entities(Chapter.id, Chapter.chapter_number, Chapter.title, Chapter.content_status,
        Chapter.document['content_version'].as_string(), func.length(Chapter.content), Chapter.chapter_key).order_by(Chapter.chapter_number).offset(offset).limit(limit)
    return dict(novel_id=novel_id, total=total, offset=offset, limit=limit, items=[dict(id=id,
        chapter_number=number, title=title, content_status=status.value, source_version=version, current_content_version=version,chapter_key=key,**manifest,
        downloaded=bool(length)) for id,number,title,status,version,length,key in rows])


def review(db, user, novel_id, value):
    from app.models.user import User
    db.query(User.id).filter_by(id=user.id).with_for_update().first()
    novel = owned_story(db, user.id, novel_id)
    provider = db.query(ReaderProvider).filter_by(id=value.provider_id,user_id=user.id).populate_existing().first()
    if provider is None:raise HTTPException(404, 'Provider not found')
    query = db.query(Chapter).filter(Chapter.novel_id==novel_id, Chapter.id.in_(value.chapter_ids))
    sizes = query.with_entities(Chapter.id,byte_length(db,Chapter.content),byte_length(db,Chapter.document)).all()
    if len(sizes)!=len(value.chapter_ids):raise HTTPException(404,'A selected chapter is missing or belongs to another story')
    if sum((text or 0)+(document or 0) for _,text,document in sizes)>MAX_BYTES:
        raise HTTPException(422,'Selected chapter content exceeds the review limit; select fewer chapters')
    error = None
    try:
        if not provider.enabled:raise ValueError('This provider is disabled')
        validate_destination(provider.kind,provider.base_url)
        if provider.supported_languages and value.language.lower() not in {language.lower() for language in provider.supported_languages}:
            raise ValueError('This provider does not support the selected language')
        processing_permissions.check(db,user.id,novel,provider,'translation',consent=value.external_consent,ao3_consent=value.ao3_consent)
    except (ValueError,PermissionError) as exc:error=str(exc)
    external=provider.kind not in {'local','local_translation'}
    permission=db.query(StoryProcessingPermission).filter_by(user_id=user.id,novel_id=novel_id,provider_id=provider.id).populate_existing().first()
    available=max(0,provider.budget_microusd-provider.used_microusd-provider.reserved_microusd)
    budget_configured=not external or bool(provider.secret_ciphertext and provider.budget_microusd and (provider.input_price or provider.output_price))
    if external and not budget_configured and error is None:error='Set an API key, prices and a spending budget before bulk translation'
    identities={item.chapter_id:item.model_dump(exclude={"chapter_id"}) for item in (value.chapter_identities or [])}
    items=[];prepared={};chapter_snapshots=[];block_count=0;estimated=0
    for chapter in query.order_by(Chapter.chapter_number).populate_existing().all():
        from app.services.translation_identity_service import capture
        captured=capture(db,user.id,chapter,identities.get(chapter.id))
        document=chapter.document or from_text(chapter.content or '')
        if not isinstance(document,dict):document={}
        blocks=document.get('blocks',[])
        if not isinstance(blocks,list):blocks=[]
        block_count+=len(blocks)
        if block_count>MAX_BLOCKS:raise HTTPException(422,'Selected chapters exceed the block limit; select fewer chapters')
        glossary=glossary_for(db,user.id,novel_id,value.language,chapter.chapter_number)
        snapshot={'kind':provider.kind,'base_url':provider.base_url,'model':provider.model}
        version=document.get('content_version') if isinstance(document,dict) else None
        fingerprint=variant_fingerprint(provider.id,version,value.language,glossary,snapshot,captured["chapter_key"],captured["manifest_epoch"])
        existing=db.query(TranslationJob).options(load_only(TranslationJob.id,TranslationJob.status)).filter_by(user_id=user.id,chapter_id=chapter.id,fingerprint=fingerprint).first()
        if existing is None:
            existing=compatible_completed(db,user_id=user.id,chapter_id=chapter.id,provider_id=provider.id,language=value.language,
                version=version,glossary=glossary,snapshot=snapshot,blocks=blocks,chapter_key=captured['chapter_key'],manifest_epoch=captured['manifest_epoch'])
        invalid=not chapter.content or not blocks or not version or any(not isinstance(block,dict) or not isinstance(block.get('text'),str) or len(block['text'].encode())>12_000 for block in blocks)
        state='unavailable' if invalid else 'already_ready' if existing and existing.status=='completed' else 'already_queued' if existing and existing.status in {'queued','processing','retry_wait'} else 'needs_retry' if existing else 'ready_to_queue'
        item_error='Download a complete chapter with paragraphs within the translation limit' if invalid else None
        estimate=0
        if state=='ready_to_queue':
            if external:
                estimate=sum(cost(provider,len(json.dumps({'language':value.language,'glossary':glossary,'text':block['text']},ensure_ascii=False).encode())+4096,MAX_OUTPUT_TOKENS) for block in blocks if block['text'].strip())
            estimated+=estimate
            if error:state,item_error='blocked',error
        items.append(dict(chapter_id=chapter.id,chapter_number=chapter.chapter_number,title=chapter.title,
            outcome=state,job_id=existing.id if existing else None,source_version=version,blocks=len(blocks),estimated_max_usd=estimate/1_000_000,error=item_error))
        chapter_state=[chapter.id,digest(document),glossary,fingerprint,chapter.content_status.value,captured,chapter.chapter_number,chapter.title]
        prepared[chapter.id]={'source_blocks':deepcopy(blocks),'source_version':version,'captured':captured,
            'chapter_title_snapshot':chapter.title,'chapter_number_snapshot':chapter.chapter_number,
            'glossary':deepcopy(glossary),'fingerprint':fingerprint,'provider_snapshot':{
                **snapshot,'pipeline_version':PIPELINE_VERSION,
                **({'image_assets':deepcopy(document['image_assets'])} if isinstance(document.get('image_assets'),dict) else {}),
                'authorization':{'external':external,'ao3':processing_permissions.is_ao3(novel)}},
            'state':chapter_state}
        chapter_snapshots.append(chapter_state)
    if external and estimated>available:
        for item in items:
            if item['outcome']=='ready_to_queue':item.update(outcome='blocked',error='The available provider budget cannot cover the selected chapters')
    request=value.model_dump(exclude={'review_token'})
    # Job status is deliberately excluded: completing or deduplicating the same
    # variant never invalidates the selected source/provider review.
    control=[user.id,novel_id,
        [provider.id,provider.enabled,provider.kind,provider.base_url,provider.model,provider.supported_languages,
         provider.secret_ciphertext,provider.input_price,provider.output_price,provider.budget_microusd],
        [permission.translation,permission.ao3_consent] if permission else None,
        [novel.url,novel.source_url,novel.novel_site],error]
    # The initial submission must still match the reviewed usage/budget state.
    # Once accepted, earlier approved jobs may start spending or reserving;
    # per-item guards cover static settings, while review() freshly checks the
    # remaining budget before each insertion and invoke() enforces atomic caps.
    guard=digest([request,chapter_snapshots,control,[provider.used_microusd,provider.reserved_microusd]])
    for entry in prepared.values():entry['guard']=digest([entry['state'],control])
    result=dict(total=len(items),items=items,provider=dict(id=provider.id,name=provider.name,kind=provider.kind,model=provider.model,external=external),
        language=value.language,permission=dict(allowed=error is None,error=error,is_ao3=processing_permissions.is_ao3(novel)),
        budget=dict(configured=budget_configured,available_usd=available/1_000_000,budget_usd=provider.budget_microusd/1_000_000,
            used_usd=provider.used_microusd/1_000_000,reserved_usd=provider.reserved_microusd/1_000_000),
        estimated_max_usd=estimated/1_000_000,queueable=sum(item['outcome']=='ready_to_queue' for item in items))
    return result,guard,novel,provider,prepared


def preview(db,user,novel_id,value):
    result,guard,*_=review(db,user,novel_id,value)
    expires=datetime.now(timezone.utc)+timedelta(minutes=REVIEW_MINUTES)
    token=jwt.encode({'type':'translation_batch_review','user_id':user.id,'novel_id':novel_id,'guard':guard,'exp':expires},settings.SECRET_KEY,algorithm=settings.ALGORITHM)
    return {**result,'review_token':token,'expires_at':expires.isoformat()}


def submit(db,user,novel_id,value):
    try:
        token=jwt.decode(value.review_token,settings.SECRET_KEY,algorithms=[settings.ALGORITHM])
        if token.get('type')!='translation_batch_review' or token.get('user_id')!=user.id or token.get('novel_id')!=novel_id:raise ValueError()
    except (JWTError,ValueError):raise HTTPException(409,'The review expired or is invalid; preview this selection again') from None
    result,guard,novel,provider,prepared=review(db,user,novel_id,value)
    if token.get('guard')!=guard:raise HTTPException(409,'Source, provider, glossary, pricing, budget or permissions changed; preview this selection again')
    queued=0
    for item in result['items']:
        if item['outcome']!='ready_to_queue':continue
        chapter_id=item['chapter_id']
        approved=prepared[chapter_id]
        # Previous items committed independently. Recheck only this item, with
        # fresh database state, before persisting the immutable approved snapshot.
        db.expire_all()
        single=value.model_copy(update={'chapter_ids':[chapter_id],
            'chapter_identities':[entry for entry in (value.chapter_identities or []) if entry.chapter_id==chapter_id] if value.chapter_identities is not None else None})
        try:
            fresh,_,_,_,fresh_prepared=review(db,user,novel_id,single)
            if approved['guard']!=fresh_prepared[chapter_id]['guard']:
                item.update(outcome='review_changed',error='Source or processing settings changed during queuing; preview this chapter again')
                continue
            current=fresh['items'][0]
            if current['outcome']!='ready_to_queue':
                item.update(current)
                continue
            job,created=_enqueue_snapshot(db,user.id,novel_id,value.provider_id,chapter_id,value.language,approved)
            state='queued' if created else 'already_ready' if job.status=='completed' else 'already_queued' if job.status in {'queued','processing','retry_wait'} else 'needs_retry'
            item.update(outcome=state,job_id=job.id)
            queued+=created
        except HTTPException as exc:
            db.rollback();item.update(outcome='review_changed',error=str(exc.detail))
        except IntegrityError:
            db.rollback();item.update(outcome='review_changed',error='A selected chapter or provider changed during queuing; preview this chapter again')
        except ValueError as exc:
            db.rollback();item.update(outcome='unavailable',error=str(exc))
    return {**result,'queued':queued}


def _enqueue_snapshot(db,user_id,novel_id,provider_id,chapter_id,language,approved):
    """Same variant identity/schema as queue_translation, using reviewed inputs.

    In particular, never refetch a newer glossary after the final review check.
    Existing workers keep paragraph resume and atomic per-invocation budgets.
    """
    from app.services.translation_identity_service import capture
    chapter=db.query(Chapter).filter_by(id=chapter_id,novel_id=novel_id).first()
    if chapter is None:raise HTTPException(409,'The selected original chapter changed')
    source=approved['captured']
    capture(db,user_id,chapter,{'expected_chapter_key':source['chapter_key'],'expected_manifest_epoch':source['manifest_epoch'],
        'expected_manifest_revision':source['manifest_revision'],'expected_content_version':source['source_version']})
    query=db.query(TranslationJob).filter_by(user_id=user_id,chapter_id=chapter_id,fingerprint=approved['fingerprint'])
    existing=query.first()
    if existing is not None:return existing,False
    job=TranslationJob(user_id=user_id,novel_id=novel_id,provider_id=provider_id,chapter_id=chapter_id,
        language=language,fingerprint=approved['fingerprint'],source_version=approved['source_version'],
        chapter_key=source['chapter_key'],manifest_epoch=source['manifest_epoch'],manifest_revision=source['manifest_revision'],
        chapter_title_snapshot=approved['chapter_title_snapshot'],chapter_number_snapshot=approved['chapter_number_snapshot'],identity_inferred=False,
        provider_snapshot=deepcopy(approved['provider_snapshot']),source_blocks=deepcopy(approved['source_blocks']),
        glossary=deepcopy(approved['glossary']),translated_blocks=[],next_attempt_at=utcnow())
    try:
        with db.begin_nested():db.add(job);db.flush()
        db.commit()
    except IntegrityError:
        db.rollback()
        existing=query.first()
        if existing is not None:return existing,False
        raise
    db.refresh(job)
    return job,True


def patch_translation_permission(db,user,novel_id,provider_id,value):
    from sqlalchemy import null
    novel=owned_story(db,user.id,novel_id)
    provider=db.query(ReaderProvider).filter_by(id=provider_id,user_id=user.id).first()
    if provider is None:raise HTTPException(404,'Provider not found')
    ao3=processing_permissions.is_ao3(novel)
    if value.translation and ao3 and not value.ao3_consent:
        raise HTTPException(422,'Explicitly authorize AO3 material before enabling external processing')
    row=db.query(StoryProcessingPermission).filter_by(user_id=user.id,novel_id=novel_id,provider_id=provider_id).first()
    if row is None:
        # NULL means no companion choice has been made; explicit false remains
        # a denial. The translation-only action must not change that choice.
        row=StoryProcessingPermission(user_id=user.id,novel_id=novel_id,provider_id=provider_id,companion=null())
        db.add(row)
    row.translation=value.translation
    if value.ao3_consent:row.ao3_consent=True
    if not value.translation:
        db.query(TranslationJob).filter(TranslationJob.user_id==user.id,TranslationJob.novel_id==novel_id,
            TranslationJob.provider_id==provider_id,TranslationJob.status.in_(['queued','processing','retry_wait'])).update(
            {'status':'cancelled','finished_at':utcnow(),'lease_owner':None,'lease_expires_at':None},synchronize_session=False)
    db.commit();db.refresh(row)
    return dict(translation=row.translation,companion=row.companion,ao3_consent=bool(row.ao3_consent),is_ao3=ao3,
        local=provider.kind in {'local','local_translation'})
