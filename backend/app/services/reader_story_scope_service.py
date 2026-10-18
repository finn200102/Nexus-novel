"""Exact, run-scoped evidence for the shared Story Guide.

A numeric reading position alone never authorizes shared analysis. Only an
ordered prefix of current rich chapters, explicitly completed this run and
confirmed by current-version receipts, can be disclosed to an upstream guide.
"""
import hashlib
from sqlalchemy import func
from app.models import Chapter, ChapterReadReceipt, Library, Novel, ReadingProgress, User
from app.services.reading_run_service import current_run, restore_progress
from app.services.reading_checkpoint_service import checkpoint_rows
from fastapi import HTTPException

MAX_CHAPTERS=20_000
MAX_TEXT_BYTES=32*1024**2
MAX_CHAPTER_BYTES=1024**2


def scope(db,user_id,metadata_id,requested=None,*,captured_identities=None):
    from app.auth.dependencies import require_current_session
    user=db.query(User).filter_by(id=user_id).populate_existing().with_for_update().first()
    if user is None or user.is_disabled:raise HTTPException(401,'Account is unavailable')
    require_current_session(db,user_id)
    novel=db.query(Novel).join(Library).filter(Novel.metadata_id==metadata_id,Library.user_id==user_id).order_by(Novel.id).first()
    empty={'through_chapter':None,'chapters':[]}
    if novel is None:return empty,None
    point=db.query(ReadingProgress).filter_by(user_id=user_id,novel_id=novel.id).populate_existing().first()
    run=current_run(db,user_id,novel.id,point)
    if point is None:point=restore_progress(run)
    if point is None or run is None:return empty,novel
    checkpoints=checkpoint_rows(db,user_id,novel.id,point,run,strong_identity=True)
    version=Chapter.document['content_version'].as_string()
    query=db.query(Chapter.id,Chapter.chapter_key,Chapter.chapter_number,Chapter.content_status,version,
        func.length(Chapter.content),ChapterReadReceipt.completed,ChapterReadReceipt.requires_review,
        checkpoints.c.max_percent).outerjoin(ChapterReadReceipt,
            (ChapterReadReceipt.chapter_id==Chapter.id)&(ChapterReadReceipt.chapter_key==Chapter.chapter_key)&(ChapterReadReceipt.user_id==user_id)&(ChapterReadReceipt.content_version==version)).outerjoin(
            checkpoints,(checkpoints.c.chapter_key==Chapter.chapter_key)&(checkpoints.c.content_version==version)).filter(Chapter.novel_id==novel.id).order_by(Chapter.chapter_number,Chapter.id)
    verified=[];total_bytes=0
    # Stop on the first unverified actual chapter, rather than skipping gaps
    # and allowing an unbounded cached overview to supply future identities.
    for id,key,number,status,current_version,length,completed,review_required,max_percent in query.yield_per(100):
        if requested is not None and number>requested:break
        if not current_version or status.value!='PRESENT' or not completed or review_required or max_percent is None or max_percent<100:break
        if len(verified)>=MAX_CHAPTERS:
            raise HTTPException(422,'Verified Story Guide scope exceeds 20,000 chapters; choose an earlier reading boundary')
        if not length:break
        if length>MAX_CHAPTER_BYTES or total_bytes+length>MAX_TEXT_BYTES:
            raise HTTPException(422,'Verified Story Guide scope exceeds its text budget; choose an earlier reading boundary')
        # Load one already-authorized chapter at a time. Never materialize an
        # entire book, future prose, prompts, provider keys or cached answers.
        actual=db.query(Chapter.content,Chapter.document['plain_text'].as_string(),version).filter_by(id=id,chapter_key=key,novel_id=novel.id).first()
        if actual is None:break
        content,plain,actual_version=actual
        if actual_version!=current_version or content!=plain:break
        size=len(content.encode('utf-8'))
        if size>MAX_CHAPTER_BYTES or total_bytes+size>MAX_TEXT_BYTES:
            raise HTTPException(422,'Verified Story Guide scope exceeds its text budget; choose an earlier reading boundary')
        total_bytes+=size
        text_hash=hashlib.sha256(' '.join(content.split()).encode('utf-8')).hexdigest()
        verified.append({'chapter_number':number,'text_sha256':text_hash})
        if captured_identities is not None:captured_identities.append((key,current_version))
    return {'through_chapter':verified[-1]['chapter_number'] if verified else None,'chapters':verified},novel


def request_snapshot(db,user_id,metadata_id,requested=None):
    """Build primitive read proof in a worker; release locks before any RPC.

    The caller must revalidate after the RPC: neither a synchronous row-lock
    wait nor a transaction spanning network awaits belongs on the event loop.
    """
    try:
        bindings=[]
        proof,novel=scope(db,user_id,metadata_id,requested,captured_identities=bindings)
        local=None
        identity=None
        if novel is not None:
            local={'library_id':novel.library_id,'novel_id':novel.id}
            point=db.query(ReadingProgress).filter_by(user_id=user_id,novel_id=novel.id).populate_existing().first()
            run=current_run(db,user_id,novel.id,point)
            from app.services.chapter_identity_service import manifest_state
            from app.services.source_refresh_guard import source_fields,manifest_binding
            state=manifest_state(db,novel.id)
            account_identity=db.query(User.storage_id).filter_by(id=user_id).scalar()
            library_identity=db.query(Library.identity_key).filter_by(id=novel.library_id,user_id=user_id).scalar()
            identity=(account_identity,library_identity,run.run_key if run else None,state.manifest_epoch,str(state.revision),
                source_fields(novel),manifest_binding(state),tuple(bindings))
        return proof,local,identity
    finally:
        db.rollback()


def empty_response(operation,metadata_id,args=None):
    args=args or {}
    result={'work_id':metadata_id,'through_chapter':None,'safe_through_chapter':None,'unavailable':False}
    if operation=='guide':return {**result,'chapters_analyzed':0,'guide_status':'empty','characters':[],'chapters':[],'encyclopedia':{},'coverage':{'claims':0,'scenes':0,'entities':0,'citations':0}}
    if operation=='projection':return {**result,'projection_version':'reader-empty-v1','coverage':{'state':'empty','chapters':0,'entities':0,'characters':0,'world_entries':0,'assertions':0,'relationships':0,'citations':0,'needs_review':0},
        'overview':{'story_so_far':[],'active_threads':[],'resolved_threads':[],'story_signals':[]},'characters':[],'world':[],'relationships':[],'timeline':[],'arcs':[],'chapter_dossiers':[],'assertions':[]}
    if operation in ('entities','relationships'):return {**result,operation:[]}
    if operation=='timeline':return {**result,'timelines':[]}
    if operation=='changes':return {**result,'from_chapter':args.get('from_chapter'),'count':0,'changes':{key:[] for key in ('characters','world','relationships','revelations','consequences','takeaways')}}
    if operation in ('article','profile'):return {**result,'entity':None,'claims':[],'facts':{},'profile':{},'developments':[]}
    if operation=='dossier':return {**result,'chapter':args.get('chapter_number'),'status':'not_yet_read','dossier':None,'assertions':[]}
    raise HTTPException(403,'Read and explicitly confirm current chapter text before using this Story Guide action')
