"""Approximate device locations never constitute verified reading evidence."""
import hashlib
import json
from datetime import datetime,UTC
from fastapi import HTTPException
from app.models import User,Novel,Library,Chapter,ReadingProgress,ReadingHistory
from app.models.reading_progress import ReadingProgressOperation
from app.services.chapter_identity_service import sqlite_transaction,manifest_state,source_version
from app.services.reading_run_service import current_run,ensure_run,restore_progress,snapshot_progress,progress_view


def digest(chapter):
    value=[chapter.content or '',chapter.document,chapter.title or f'Chapter {chapter.chapter_number}']
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()



def source_snapshot(db,novel):
    from app.services.source_refresh_guard import source_fields
    state=manifest_state(db,novel.id)
    return {'source_fields':list(source_fields(novel)),'metadata_manifest_key':state.metadata_manifest_key,'metadata_source':state.metadata_source}


def owner(db,user_id,novel_id):
    sqlite_transaction(db,write=True)
    user=db.query(User).filter_by(id=user_id).populate_existing().with_for_update().first()
    if user is None or user.is_disabled:raise HTTPException(404,'Story not found')
    from app.auth.dependencies import require_current_session
    require_current_session(db,user_id)
    novel=db.query(Novel).join(Library).filter(Novel.id==novel_id,Library.user_id==user_id).populate_existing().with_for_update(of=Novel).first()
    if novel is None:raise HTTPException(404,'Story not found')
    return user,novel


def proof_chapter(db,user_id,build,index,*,lock=False):
    user,novel=owner(db,user_id,build.novel_id)
    if (build.owner_storage_id!=user.storage_id or not build.source_snapshot or build.source_snapshot!=source_snapshot(db,novel) or not isinstance(build.spine_identity,list)
            or type(index) is not int or not 0<=index<len(build.spine_identity)):
        return None,'book_identity_unknown'
    captured=build.spine_identity[index]
    if not isinstance(captured,dict):return None,'book_identity_unknown'
    query=db.query(Chapter).filter_by(novel_id=novel.id,chapter_key=captured.get('chapter_key'),archived=False).populate_existing()
    if lock:query=query.with_for_update()
    chapter=query.first()
    state=manifest_state(db,novel.id,lock=lock)
    if state.manifest_epoch!=build.manifest_epoch:return None,'book_lifecycle_changed'
    if chapter is None:return None,'book_chapter_changed'
    if source_version(chapter)!=captured.get('source_version') or digest(chapter)!=captured.get('body_sha256'):
        return None,'book_content_changed'
    return chapter,None


def inferred(db,user_id,build,index,fraction,*,operation,approved_run_key=None):
    """Caller commits bookmark and inferred point together. No receipts/time/completion."""
    chapter,reason=proof_chapter(db,user_id,build,index,lock=True)
    if reason:return reason
    progress=db.query(ReadingProgress).filter_by(user_id=user_id,novel_id=build.novel_id).populate_existing().first()
    run=current_run(db,user_id,build.novel_id,progress)
    expected=approved_run_key if approved_run_key is not None else build.reading_run_key
    if expected is not None and (run is None or run.run_key!=expected):return 'reading_run_changed'
    if expected is None and run is not None and (run.requires_run_key or run.ordinal!=1):return 'reading_run_changed'
    if run is None:run=ensure_run(db,user_id,build.novel_id,legacy=True)
    if build.reading_run_key is None:build.reading_run_key=run.run_key
    if progress is None:progress=restore_progress(run)
    if progress is None:
        progress=ReadingProgress(user_id=user_id,novel_id=build.novel_id);db.add(progress)
    elif progress not in db:db.add(progress)
    receipt_key='ereader:'+hashlib.sha256(operation.encode()).hexdigest()
    if db.query(ReadingProgressOperation.id).filter_by(user_id=user_id,operation_id=receipt_key).first():return None
    percent=min(max(float(fraction)*100,0),100)
    # Device packets lack an explicit rewind intent. Preserve an already later
    # private place; its original device bookmark is still stored by callers.
    if progress.chapter_number is not None and (progress.chapter_number,progress.percent or 0)>=(chapter.chapter_number,percent):
        db.add(ReadingProgressOperation(user_id=user_id,novel_id=build.novel_id,operation_id=receipt_key,
            fingerprint=hashlib.sha256(operation.encode()).hexdigest(),response=progress_view(progress)))
        return None
    state=manifest_state(db,build.novel_id)
    progress.chapter_id=chapter.id;progress.chapter_key=chapter.chapter_key;progress.chapter_number=chapter.chapter_number
    progress.current_identity_inferred=True;progress.manifest_epoch=state.manifest_epoch;progress.manifest_revision=str(state.revision)
    progress.source_content_version=source_version(chapter);progress.position=0;progress.percent=percent
    progress.reading_run_key=run.run_key;progress.revision=(progress.revision or 0)+1
    progress.block_id=None;progress.text_offset=0;progress.text_quote=None;progress.quote_prefix=None;progress.quote_suffix=None
    progress.locator_content_version=None;progress.locator_variant=None
    if progress.furthest_chapter_key is None or (chapter.chapter_number,percent)>(progress.furthest_chapter_number,progress.furthest_percent or 0):
        progress.furthest_chapter_key=chapter.chapter_key;progress.furthest_chapter_number=chapter.chapter_number;progress.furthest_percent=percent
        progress.furthest_content_version=source_version(chapter);progress.furthest_identity_inferred=1
    day=datetime.now(UTC).replace(tzinfo=None,hour=0,minute=0,second=0,microsecond=0)
    history=db.query(ReadingHistory).filter_by(user_id=user_id,novel_id=build.novel_id,chapter_key=chapter.chapter_key,reading_run_key=run.run_key,reading_date=day).first()
    if history is None:
        db.add(ReadingHistory(user_id=user_id,novel_id=build.novel_id,chapter_key=chapter.chapter_key,chapter_number=chapter.chapter_number,
            reading_run_key=run.run_key,reading_date=day,max_percent=int(percent),identity_inferred=True,verified_percent=0))
    elif history.identity_inferred:history.max_percent=max(history.max_percent or 0,int(percent))
    db.flush();run.progress_snapshot=snapshot_progress(run,progress)  # deliberately no update_run/mark_complete
    db.add(ReadingProgressOperation(user_id=user_id,novel_id=build.novel_id,operation_id=receipt_key,
        fingerprint=hashlib.sha256(operation.encode()).hexdigest(),response=progress_view(progress)))
    return None


def progress_index(db,user_id,build,progress):
    if progress is None or not isinstance(build.spine_identity,list):return None
    run=current_run(db,user_id,build.novel_id,progress)
    if build.reading_run_key is not None and build.reading_run_key!=progress.reading_run_key:return None
    if build.reading_run_key is None and run is not None and (run.requires_run_key or run.ordinal!=1):return None
    for index,item in enumerate(build.spine_identity):
        if item.get('chapter_key')==progress.chapter_key:
            chapter,reason=proof_chapter(db,user_id,build,index)
            if reason:return None
            return index,min(max((progress.percent or 0)/100,0),1)
    return None
