"""SQL counts and bounded pages for the private story reading overview."""
from fastapi import HTTPException
from sqlalchemy import case, cast, String, func, or_
from sqlalchemy.orm import defer
from app.models import Chapter, Novel, Library, User, ReadingProgress, NovelPersonalData
from app.models.reading_continuity import ReadingContinuity
from app.services.reading_run_service import current_run, restore_progress
from app.services.reading_checkpoint_service import checkpoint_rows, category_expression
from app.services.library_organization_service import followed_categories_of


def context(db, user_id, novel_id):
    if db.query(Novel.id).join(Library).filter(Novel.id==novel_id, Library.user_id==user_id).first() is None:
        raise HTTPException(404, 'Novel not found')
    # Serialize the short aggregate/read transaction with progress/reread and
    # preference writes, returning one coherent revision and checkpoint set.
    db.query(User.id).filter_by(id=user_id).with_for_update().first()
    point = db.query(ReadingProgress).filter_by(user_id=user_id, novel_id=novel_id).populate_existing().first()
    run = current_run(db,user_id,novel_id,point)
    if point is None:point=restore_progress(run)
    personal = db.query(NovelPersonalData).filter_by(user_id=user_id,novel_id=novel_id).first()
    categories = followed_categories_of(personal)
    current = None
    if point is not None and point.chapter_number is not None:
        query=db.query(Chapter.id,Chapter.chapter_number,Chapter.category).filter_by(novel_id=novel_id)
        if point.chapter_key is not None:
            current=query.filter(Chapter.chapter_key==point.chapter_key).first()
        else:
            from app.services.chapter_identity_service import manifest_state
            if not manifest_state(db,novel_id).identity_required:
                current=query.filter(Chapter.id==point.chapter_id).first() if point.chapter_id is not None else query.filter(Chapter.chapter_number==point.chapter_number).first()
    checkpoints=checkpoint_rows(db,user_id,novel_id,point,run,current_number=current.chapter_number if current else None)
    return point,run,categories,current,checkpoints


def summary(db,user_id,novel_id):
    point,run,categories,current,checkpoints=context(db,user_id,novel_id)
    followed=category_expression().in_(categories)
    completed=func.coalesce(checkpoints.c.max_percent,0)>=95
    query=db.query(Chapter).filter(Chapter.novel_id==novel_id).outerjoin(checkpoints,checkpoints.c.chapter_number==Chapter.chapter_number)
    counts=query.with_entities(func.count(Chapter.id),func.coalesce(func.sum(case((followed,1),else_=0)),0),
        func.coalesce(func.sum(case((completed,1),else_=0)),0),
        func.coalesce(func.sum(case((followed & completed,1),else_=0)),0)).one()
    current_view=None
    if point is not None and point.chapter_number is not None:
        ordinal=followed_ordinal=None
        if current is not None:
            before=db.query(Chapter).filter(Chapter.novel_id==novel_id,Chapter.chapter_number<=current.chapter_number)
            ordinal=before.with_entities(func.count(Chapter.id)).scalar()
            if ((current.category or 'story').strip().lower() or 'story') in categories:
                followed_ordinal=before.filter(category_expression().in_(categories)).with_entities(func.count(Chapter.id)).scalar()
        current_view=dict(chapter_id=current.id if current else None,chapter_number=current.chapter_number if current else point.chapter_number,
            ordinal=ordinal,followed_ordinal=followed_ordinal,percent=float(point.percent or 0))
    completed_reading=False
    if run is not None:
        if run.continuity_key:
            completed_reading=bool(db.query(ReadingContinuity.completed).filter_by(user_id=user_id,continuity_key=run.continuity_key).scalar())
        else:completed_reading=bool(run.completed_at is not None or run.completed_at_inferred)
    # Share the reading-order policy, including its explicitly inferred legacy
    # branch, rather than offering a competing Continue destination.
    from app.services.reading_order import next_unread_for_run
    following=next_unread_for_run(db,user_id,novel_id,point,run)
    category_rows=db.query(category_expression()).filter(Chapter.novel_id==novel_id).distinct().order_by(category_expression()).limit(257).all()
    return dict(novel_id=novel_id,reading_run_key=run.run_key if run else None,revision=(point.revision or 0) if point else 0,
        categories=[row[0] for row in category_rows[:256]],categories_truncated=len(category_rows)>256,total_chapters=counts[0],followed_total=counts[1],completed_chapters=counts[2],followed_completed_chapters=counts[3],
        completion_basis='recorded_checkpoints',completed_reading=completed_reading,current=current_view,
        next_unread_chapter_id=following.id if following else None,next_unread_chapter_number=following.chapter_number if following else None)


def page(db,user_id,novel_id,offset,limit,q='',category_scope='all',from_chapter=None,to_chapter=None):
    point,run,categories,current,checkpoints=context(db,user_id,novel_id)
    from app.services.chapter_identity_service import manifest_state,state_fields
    header=state_fields(manifest_state(db,novel_id))
    followed=category_expression().in_(categories)
    # Window ordinals are calculated BEFORE filters/pagination. Chapter 7 may
    # legitimately be item 2 of 3, including on a later search result page.
    ordering=(Chapter.chapter_number,Chapter.id)
    ordinals=db.query(Chapter.id.label('id'),func.row_number().over(order_by=ordering).label('ordinal'),
        func.sum(case((followed,1),else_=0)).over(order_by=ordering,rows=(None,0)).label('followed_ordinal')).filter(Chapter.novel_id==novel_id).subquery()
    query=db.query(Chapter,ordinals.c.ordinal,ordinals.c.followed_ordinal,checkpoints.c.max_percent).join(
        ordinals,ordinals.c.id==Chapter.id).outerjoin(checkpoints,checkpoints.c.chapter_number==Chapter.chapter_number).filter(Chapter.novel_id==novel_id)
    if from_chapter is not None and to_chapter is not None and from_chapter>to_chapter:raise HTTPException(422,'Choose chapter numbers in ascending order')
    if from_chapter is not None:query=query.filter(Chapter.chapter_number>=from_chapter)
    if to_chapter is not None:query=query.filter(Chapter.chapter_number<=to_chapter)
    if category_scope=='followed':query=query.filter(followed)
    if q:
        pattern='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        query=query.filter(or_(Chapter.title.ilike(pattern,escape='\\'),cast(Chapter.chapter_number,String).ilike(pattern,escape='\\')))
    total=query.with_entities(Chapter.id).count()
    rows=query.options(defer(Chapter.content),defer(Chapter.document)).order_by(Chapter.chapter_number,Chapter.id).offset(offset).limit(limit).all()
    fields=[column.name for column in Chapter.__table__.columns if column.name not in ('content','document')]
    items=[]
    for chapter,ordinal,followed_ordinal,percent in rows:
        is_followed=((chapter.category or 'story').strip().lower() or 'story') in categories
        items.append({**{key:getattr(chapter,key) for key in fields},**header,'ordinal':ordinal,'category':((chapter.category or 'story').strip().lower() or 'story'),
            'followed_ordinal':followed_ordinal if is_followed else None,'followed':is_followed,
            'completed_checkpoint':percent is not None and percent>=95,'max_percent':percent})
    return dict(novel_id=novel_id,reading_run_key=run.run_key if run else None,revision=(point.revision or 0) if point else 0,
        total=total,offset=offset,limit=limit,items=items)
