"""Private, exact-version read evidence without numeric range inference."""
from dataclasses import dataclass
from types import SimpleNamespace
from fastapi import HTTPException
from sqlalchemy import func, cast, Text, or_
from app.models import Chapter,ChapterReadReceipt,Novel,Library,ReadingProgress,User
from app.services.reading_checkpoint_service import checkpoint_rows
from app.services.reading_run_service import current_run,restore_progress
from app.services.chapter_document import from_text,content_version

MAX_CHAPTERS=20_000
MAX_BYTES=32*1024**2
MAX_CHAPTER_BYTES=1024**2


@dataclass
class ReadScope:
    run_key:str|None
    revision:int
    through_chapter:int|None=None


def verified_chapters(db,user_id,novel_id,requested=None,*,descending=False,max_verified=None,chapter_ids=None):
    """Return a scope and one-pass iterator; never read an unapproved body.

    Completed checkpoints are per-run. Lifetime receipts alone do not authorize
    a reread, and prior content editions cannot authorize current blocks.
    """
    if db.query(Novel.id).join(Library).filter(Novel.id==novel_id,Library.user_id==user_id).first() is None:
        raise HTTPException(404,'Story not found')
    db.query(User.id).filter_by(id=user_id).with_for_update().first()
    point=db.query(ReadingProgress).filter_by(user_id=user_id,novel_id=novel_id).populate_existing().first()
    run=current_run(db,user_id,novel_id,point)
    if point is None:point=restore_progress(run)
    state=ReadScope(run.run_key if run else None,(point.revision or 0) if point else 0)
    if run is None:return state,iter(())
    checkpoints=checkpoint_rows(db,user_id,novel_id,point,run,strong_identity=True)
    from app.services.chapter_identity_service import manifest_state, state_fields
    header=state_fields(manifest_state(db,novel_id))
    version=Chapter.document['content_version'].as_string()
    eligible_receipt=db.query(ChapterReadReceipt.id).filter(ChapterReadReceipt.user_id==user_id,
        ChapterReadReceipt.chapter_id==Chapter.id,ChapterReadReceipt.chapter_key==Chapter.chapter_key,ChapterReadReceipt.completed.is_(True),ChapterReadReceipt.requires_review.is_(False),
        or_(version.is_(None),ChapterReadReceipt.content_version==version)).exists()
    query=db.query(Chapter.id,Chapter.chapter_key,Chapter.chapter_number,Chapter.title,version,checkpoints.c.content_version,func.length(Chapter.content),
        func.length(cast(Chapter.document['blocks'],Text))).join(checkpoints,checkpoints.c.chapter_key==Chapter.chapter_key).filter(
            Chapter.novel_id==novel_id,checkpoints.c.max_percent>=100,eligible_receipt,
            or_(version.is_(None),checkpoints.c.content_version==version))
    if requested is not None:query=query.filter(Chapter.chapter_number<=requested)
    if chapter_ids is not None:
        if len(chapter_ids)>MAX_CHAPTERS:
            raise HTTPException(422,'Read evidence exceeds 20,000 selected chapters')
        query=query.filter(Chapter.id.in_(chapter_ids))
    query=query.order_by(Chapter.chapter_number.desc(),Chapter.id.desc()) if descending else query.order_by(Chapter.chapter_number,Chapter.id)
    def iterate():
        total=count=accepted=0
        for id,chapter_key,number,title,stored_version,verified_version,text_size,block_size in query.yield_per(50):
            count+=1
            if count>MAX_CHAPTERS:raise HTTPException(422,'Read evidence exceeds 20,000 chapters; choose an earlier reading boundary')
            estimate=(text_size or 0)+(block_size or 0)
            if estimate>MAX_CHAPTER_BYTES or total+estimate>MAX_BYTES:
                raise HTTPException(422,'Read evidence exceeds its text budget; choose an earlier reading boundary')
            # JSON projections exclude image assets and every unapproved chapter.
            actual_key,text,blocks,plain,actual_version=db.query(Chapter.chapter_key,Chapter.content,Chapter.document['blocks'],
                Chapter.document['plain_text'].as_string(),version).filter_by(id=id,novel_id=novel_id).one()
            if actual_key!=chapter_key or actual_version!=stored_version:continue
            if actual_version is None:
                document=from_text(text or '')
            else:
                if not isinstance(blocks,list) or plain!=text:continue
                if any(not isinstance(block,dict) or not isinstance(block.get('html'),str) or not isinstance(block.get('text'),str) or not isinstance(block.get('id'),str) for block in blocks):continue
                if content_version(blocks)!=actual_version:continue
                document={'content_version':actual_version,'blocks':blocks,'plain_text':plain}
            if not document['blocks'] or document['content_version']!=verified_version:continue
            confirmed=db.query(ChapterReadReceipt.id).filter_by(user_id=user_id,chapter_id=id,chapter_key=chapter_key,
                content_version=document['content_version'],completed=True,requires_review=False).first()
            if confirmed is None:continue
            import json
            size=len((text or '').encode())+len(json.dumps(document['blocks'],ensure_ascii=False).encode())
            total+=size
            if size>MAX_CHAPTER_BYTES or total>MAX_BYTES:
                raise HTTPException(422,'Read evidence exceeds its text budget; choose an earlier reading boundary')
            state.through_chapter=max(state.through_chapter,number) if state.through_chapter is not None else number
            accepted+=1
            yield SimpleNamespace(id=id,chapter_key=chapter_key,chapter_number=number,title=title,document=document,**header)
            if max_verified is not None and accepted>=max_verified:break
    return state,iterate()
