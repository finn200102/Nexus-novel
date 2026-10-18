"""Run checkpoints keyed by immutable chapter lifecycle, never ordinal ranges."""
from sqlalchemy import func, literal, union_all, and_, or_
from app.models.reading_history import ReadingHistory
from app.models.chapter import Chapter
from app.models.chapter_manifest import ChapterManifestState


def category_expression():
    return func.coalesce(func.nullif(func.lower(func.trim(Chapter.category)),''),'story')


def checkpoint_rows(db, user_id, novel_id, progress, run, *, current_number=None, strong_identity=False):
    """SQL relation (chapter_key, chapter_number, content_version, max_percent).

    Strong evidence excludes every inferred or unresolved historical binding.
    UI counts may retain an inferred binding; pre-topology legacy counts may
    resolve a numeric label for display only. This never rewrites its history.
    """
    required=bool(db.query(ChapterManifestState.identity_required).filter_by(novel_id=novel_id).scalar())
    legacy=not strong_identity and not required
    join=and_(Chapter.novel_id==novel_id,or_(
        and_(ReadingHistory.chapter_key.is_not(None),ReadingHistory.chapter_key==Chapter.chapter_key),
        and_(ReadingHistory.chapter_key.is_(None),ReadingHistory.chapter_number==Chapter.chapter_number) if legacy else literal(False)))
    history=db.query(Chapter.chapter_key.label('chapter_key'),Chapter.chapter_number.label('chapter_number'),
        (ReadingHistory.verified_percent if strong_identity else ReadingHistory.max_percent).label('max_percent'),
        (ReadingHistory.verified_content_version if strong_identity else literal(None)).label('content_version')).join(Chapter,join).filter(
        ReadingHistory.user_id==user_id,ReadingHistory.novel_id==novel_id,
        ReadingHistory.reading_run_key==(run.run_key if run is not None else None))
    if strong_identity:
        history=history.filter(ReadingHistory.chapter_key.is_not(None),ReadingHistory.identity_inferred.is_(False),
            ReadingHistory.verified_content_version.is_not(None),or_(Chapter.document['content_version'].as_string().is_(None),
                Chapter.document['content_version'].as_string()==ReadingHistory.verified_content_version))
    pieces=[history.statement]

    def add(key, number, percent, inferred=False, chapter_id=None, content_version=None):
        if strong_identity and (inferred or key is None or content_version is None):
            return
        query=db.query(Chapter.chapter_key,Chapter.chapter_number,Chapter.document['content_version'].as_string().label('current_content_version')).filter(Chapter.novel_id==novel_id)
        if key is not None:
            row=query.filter(Chapter.chapter_key==key).first()
        elif not required and chapter_id is not None:
            row=query.filter(Chapter.id==chapter_id).first()
        elif legacy and number is not None:
            row=query.filter(Chapter.chapter_number==number).first()
        else:
            return
        if row is not None and (not strong_identity or row.current_content_version is None or row.current_content_version==content_version):
            pieces.append(db.query(literal(row.chapter_key).label('chapter_key'),literal(row.chapter_number).label('chapter_number'),
                literal(float(percent or 0)).label('max_percent'),literal(content_version if strong_identity else None).label('content_version')).statement)
    if progress is not None:
        add(getattr(progress,'chapter_key',None),progress.chapter_number,progress.percent,
            bool(getattr(progress,'current_identity_inferred',False)),getattr(progress,'chapter_id',None),getattr(progress,'source_content_version',None))
        furthest=progress.furthest_chapter_number
        percent=float(progress.furthest_percent or 0)
        if getattr(progress,'furthest_chapter_key',None) is not None or (furthest is not None and (furthest!=0 or percent>0)):
            add(getattr(progress,'furthest_chapter_key',None),furthest,percent,bool(getattr(progress,'furthest_identity_inferred',False)),content_version=getattr(progress,'furthest_content_version',None))
    combined=union_all(*pieces).subquery()
    return db.query(combined.c.chapter_key,combined.c.chapter_number,combined.c.content_version,func.max(combined.c.max_percent).label('max_percent')).group_by(
        combined.c.chapter_key,combined.c.chapter_number,combined.c.content_version).subquery()
