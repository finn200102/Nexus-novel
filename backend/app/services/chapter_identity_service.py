"""Chapter identity fences; numeric labels are never stable write authority."""
from fastapi import HTTPException
from app.models import Chapter, User, Novel, Library
from app.models.chapter_manifest import ChapterManifestState
from app.services.chapter_document import from_text


def conflict(code, message, current=None):
    raise HTTPException(409, detail={'code':code,'message':message,**({'current':current} if current is not None else {})},
                        headers={'Cache-Control':'private, no-store'})


def manifest_state(db, novel_id, *, lock=False):
    query=db.query(ChapterManifestState).filter_by(novel_id=novel_id).populate_existing()
    if lock:query=query.with_for_update()
    row=query.first()
    if row is None:
        raise HTTPException(503,detail={'code':'chapter_identity_not_ready','message':'Complete the chapter identity migration before reading this chapter.'})
    return row


def state_fields(row):
    return {'manifest_epoch':row.manifest_epoch,'manifest_revision':str(row.revision)}


def identity(chapter):
    state=chapter.novel.manifest_state if chapter.novel else None
    if not chapter.chapter_key or state is None:
        raise HTTPException(503,detail={'code':'chapter_identity_not_ready','message':'Complete the chapter identity migration.'})
    return {'chapter_key':chapter.chapter_key,**state_fields(state)}


def source_version(chapter):
    return (chapter.document or from_text(chapter.content or ''))['content_version']


def guard_read(db, chapter, expected_chapter_key=None):
    if chapter.archived:
        conflict('chapter_archived','This chapter is preserved in the archive and no longer has this active address.')
    if expected_chapter_key is not None and expected_chapter_key!=chapter.chapter_key:
        conflict('chapter_manifest_changed','This chapter address now belongs to a different chapter. Refresh the chapter list.',identity(chapter))
    return chapter


def sqlite_transaction(db, *, write=False):
    # pysqlite's legacy transaction mode does not BEGIN for SELECT. Explicit
    # transactions close the check/flush race instead of merely pretending a
    # FOR UPDATE clause (ignored by SQLite) serialized a content revision.
    if db.get_bind().dialect.name=='sqlite':
        connection=db.connection()
        raw=connection.connection.driver_connection
        if not raw.in_transaction:
            connection.exec_driver_sql('BEGIN IMMEDIATE' if write else 'BEGIN')


def check_write(db, user_id, chapter, *, expected_chapter_key=None, expected_manifest_epoch=None,
                expected_manifest_revision=None, expected_content_version=None, require_content_version=False):
    """Serialize ownership -> chapter -> story counter before checking inputs.

    Topology reviewers lock all jobs, chapters, then this same counter. A source
    download cannot revise the checked text between this fence and commit.
    Internal callers must not manufacture expected keys for old device writes.
    """
    sqlite_transaction(db,write=True)
    user=db.query(User).filter_by(id=user_id).populate_existing().with_for_update().first()
    if user is None or user.is_disabled:raise HTTPException(401,'Account is unavailable')
    from app.auth.dependencies import require_current_session
    require_current_session(db,user_id)
    fresh=db.query(Chapter).execution_options(include_archived_chapters=True).join(Novel,Novel.id==Chapter.novel_id).join(Library,Library.id==Novel.library_id).filter(
        Chapter.id==chapter.id,Chapter.novel_id==chapter.novel_id,Library.user_id==user_id).populate_existing().with_for_update(of=Chapter).first()
    if fresh is None:
        raise HTTPException(404,'Chapter not found')
    if fresh.archived:
        conflict('chapter_archived','This chapter is archived. Its originals and historical reading state are preserved.')
    state=manifest_state(db,fresh.novel_id,lock=True)
    current={'chapter_key':fresh.chapter_key,'chapter_number':fresh.chapter_number,**state_fields(state),
             'source_version':source_version(fresh)}
    supplied=(expected_chapter_key,expected_manifest_epoch,expected_manifest_revision)
    modern=any(value is not None for value in supplied)
    if state.identity_required and not modern:
        conflict('chapter_identity_required','This story changed chapter order. Review this saved position instead of applying its old chapter number.',current)
    if modern:
        if any(value is None for value in supplied):
            conflict('chapter_identity_required','Supply the complete captured chapter identity and manifest revision.',current)
        if expected_chapter_key!=fresh.chapter_key or expected_manifest_epoch!=state.manifest_epoch or expected_manifest_revision!=str(state.revision):
            conflict('chapter_manifest_changed','The chapter list changed. Both reading positions have been kept; review before retrying.',current)
        if require_content_version and expected_content_version is None:
            conflict('chapter_identity_required','Supply the original source version captured with this chapter.',current)
    if expected_content_version is not None and expected_content_version!=current['source_version']:
        conflict('content_changed','The source text changed. Review the current original before applying this position or generating a derivative.',current)
    return current
