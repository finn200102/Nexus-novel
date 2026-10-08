from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session
from typing import Optional
from app.auth.dependencies import get_current_user
from config.database import get_db
from app.models.novel import Novel
from app.models.reading_progress import ReadingProgress
from app.models.user import User
from app.services import metadata_client

router = APIRouter(
    prefix="/discovery",
    tags=["discovery"],
    responses={404: {"description": "Not found"}},
)


def _reader_novel(
    db: Session,
    *,
    current_user: User,
    metadata_novel_id: int,
) -> Novel | None:
    """Return this user's copy of a metadata work, never another user's copy."""
    return (
        db.query(Novel)
        .join(Novel.library)
        .filter(Novel.metadata_id == metadata_novel_id)
        .filter(Novel.library.has(user_id=current_user.id))
        .order_by(Novel.id.asc())
        .first()
    )


def _reader_safe_cutoff(
    db: Session,
    *,
    current_user: User,
    metadata_novel_id: int,
    requested_cutoff: int | None,
) -> int:
    """Never let a Story Guide query widen beyond this user's saved progress."""
    local_novel = _reader_novel(db, current_user=current_user, metadata_novel_id=metadata_novel_id)
    if not local_novel:
        return 0
    progress = (
        db.query(ReadingProgress)
        .filter(ReadingProgress.user_id == current_user.id, ReadingProgress.novel_id == local_novel.id)
        .first()
    )
    # Opening chapter 12 is not the same as having finished chapter 12.  A
    # guide is allowed to disclose only completed chapters; this keeps the
    # current chapter's reveals out of every dossier and recap by default.
    completed = int(progress.chapter_number or 0) if progress and float(progress.percent or 0) >= .95 else max(0, int(progress.chapter_number or 0) - 1) if progress else 0
    return min(completed, requested_cutoff) if requested_cutoff is not None else completed


@router.get("/novels/")
async def get_novels(
    site: Optional[str] = Query(
        None,
        description="Filter by site: royalroad, fanfiction, webnovel, archive, spacebattles, sufficientvelocity, questionablequesting, scribblehub",
    ),
    author: Optional[str] = Query(None, description="Filter by author name"),
    title: Optional[str] = Query(None, description="Search by title"),
    tag: Optional[list[str]] = Query(None, description="Source tag contains (repeatable)"),
    tag_mode: str = Query("all", pattern="^(all|any)$", description="all or any for repeated tag, fandom and genre values"),
    fandom: Optional[list[str]] = Query(None, description="Fandom contains (repeatable)"),
    genre: Optional[list[str]] = Query(None, description="Source genre contains (repeatable)"),
    exclude_tag: Optional[list[str]] = Query(None, description="Hide exact source tag (repeatable)"),
    exclude_fandom: Optional[list[str]] = Query(None, description="Hide exact fandom (repeatable)"),
    exclude_genre: Optional[list[str]] = Query(None, description="Hide exact genre (repeatable)"),
    exclude_author: Optional[list[str]] = Query(None, description="Hide exact author name (repeatable)"),
    exclude_text: Optional[list[str]] = Query(None, description="Hide works whose title or summary contains this (repeatable)"),
    language: Optional[list[str]] = Query(None, description="Detected language (repeatable)"),
    complete_only: bool = Query(False, description="Only completed works"),
    crossover: Optional[bool] = Query(None, description="true for multi-fandom works, false for single-fandom"),
    status: Optional[str] = Query(None, description="Filter by publication status"),
    min_word_count: Optional[int] = Query(None, ge=0),
    min_favorites: Optional[int] = Query(None, ge=0),
    min_follows: Optional[int] = Query(None, ge=0),
    min_reviews: Optional[int] = Query(None, ge=0),
    min_chapter_count: Optional[int] = Query(None, ge=0),
    max_word_count: Optional[int] = Query(None, ge=0),
    updated_since_days: Optional[int] = Query(None, ge=1, le=3650),
    label: Optional[str] = Query(None),
    label_origin: Optional[str] = Query(None, pattern="^(source|ai|user|community)$"),
    import_state: Optional[str] = Query(None, pattern="^(ready|in_progress)$"),
    similar_to: Optional[int] = Query(None, ge=1, description="Return works similar to this Nexus work"),
    sort_by: str = Query("updated"),
    sort_order: str = Query("desc", pattern="^(asc|desc)$"),
    limit: int = Query(20, ge=1, le=100, description="Max items to return"),
    cursor: Optional[int] = Query(None, description="Pagination cursor"),
    current_user: User = Depends(get_current_user),
):
    """Get novels from metadata server with optional filtering."""
    data = await metadata_client.list_novels_metadata(
        site=site,
        author=author,
        title=title,
        tag=tag,
        tag_mode=tag_mode,
        fandom=fandom,
        genre=genre,
        exclude_tag=exclude_tag,
        exclude_fandom=exclude_fandom,
        exclude_genre=exclude_genre,
        exclude_author=exclude_author,
        exclude_text=exclude_text,
        language=language,
        complete_only=complete_only,
        crossover=crossover,
        status=status,
        min_word_count=min_word_count,
        min_favorites=min_favorites,
        min_follows=min_follows,
        min_reviews=min_reviews,
        min_chapter_count=min_chapter_count,
        max_word_count=max_word_count,
        updated_since_days=updated_since_days,
        label=label,
        label_origin=label_origin,
        import_state=import_state,
        similar_to=similar_to,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        cursor=cursor,
    )
    return data


@router.get("/novels/{novel_id}")
async def get_novel_by_id(
    novel_id: int,
    current_user: User = Depends(get_current_user),
):
    """Get a single novel's details from metadata server."""
    data = await metadata_client.get_novel_metadata(novel_id)
    return data


@router.get("/novels/{novel_id}/analysis")
async def get_novel_analysis(novel_id: int, current_user: User = Depends(get_current_user)):
    return await metadata_client.get_novel_analysis(novel_id)


@router.post("/novels/{novel_id}/analysis/enqueue")
async def enqueue_novel_analysis(novel_id: int, current_user: User = Depends(get_current_user)):
    """Queue local-only metadata analysis without blocking the detail page."""
    return await metadata_client.enqueue_novel_analysis(novel_id)


@router.get("/novels/{novel_id}/similar")
async def get_similar_novels(
    novel_id: int,
    limit: int = Query(8, ge=1, le=24),
    current_user: User = Depends(get_current_user),
):
    return await metadata_client.get_similar_novels(novel_id, limit)


@router.get("/novels/{novel_id}/story-guide")
async def get_story_guide(novel_id: int, through_chapter: int | None = Query(None, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await metadata_client.get_story_guide(novel_id, _reader_safe_cutoff(db, current_user=current_user, metadata_novel_id=novel_id, requested_cutoff=through_chapter))


@router.get("/novels/{novel_id}/story-guide/entities")
async def get_story_guide_entities(novel_id: int, through_chapter: int | None = Query(None, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    cutoff = _reader_safe_cutoff(db, current_user=current_user, metadata_novel_id=novel_id, requested_cutoff=through_chapter)
    return await metadata_client.get_story_guide_entities(novel_id, cutoff)


@router.get("/novels/{novel_id}/story-guide/relationships")
async def get_story_guide_relationships(novel_id: int, through_chapter: int | None = Query(None, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    cutoff = _reader_safe_cutoff(db, current_user=current_user, metadata_novel_id=novel_id, requested_cutoff=through_chapter)
    return await metadata_client.get_story_guide_relationships(novel_id, cutoff)


@router.get("/novels/{novel_id}/story-guide/projection")
async def get_story_guide_projection(novel_id: int, through_chapter: int | None = Query(None, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Professional reader-safe wiki data. The authenticated progress clamps every request."""
    cutoff = _reader_safe_cutoff(db, current_user=current_user, metadata_novel_id=novel_id, requested_cutoff=through_chapter)
    projection = await metadata_client.get_story_guide_projection(novel_id, cutoff)
    local_novel = _reader_novel(db, current_user=current_user, metadata_novel_id=novel_id)
    if local_novel:
        # User-owned route context, not shared catalog metadata. It lets cited
        # facts open only the caller's own downloaded reader copy.
        projection["reader_context"] = {"library_id": local_novel.library_id, "novel_id": local_novel.id}
    return projection


@router.get("/novels/{novel_id}/story-guide/changes")
async def get_story_guide_changes(novel_id: int, from_chapter: int = Query(0, ge=0), through_chapter: int | None = Query(None, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    cutoff = _reader_safe_cutoff(db, current_user=current_user, metadata_novel_id=novel_id, requested_cutoff=through_chapter)
    return await metadata_client.get_story_guide_changes(novel_id, min(from_chapter, cutoff), cutoff)


@router.get("/novels/{novel_id}/story-guide/entities/{entity_id}/profile")
async def get_story_guide_entity_profile(novel_id: int, entity_id: str, through_chapter: int | None = Query(None, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    cutoff = _reader_safe_cutoff(db, current_user=current_user, metadata_novel_id=novel_id, requested_cutoff=through_chapter)
    return await metadata_client.get_story_guide_entity_profile(novel_id, entity_id, cutoff)


@router.get("/novels/{novel_id}/story-guide/relationships/timeline")
async def get_story_guide_relationship_timeline(novel_id: int, through_chapter: int | None = Query(None, ge=0), entity_id: str | None = Query(None), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    cutoff = _reader_safe_cutoff(db, current_user=current_user, metadata_novel_id=novel_id, requested_cutoff=through_chapter)
    return await metadata_client.get_story_guide_relationship_timeline(novel_id, cutoff, entity_id)


@router.get("/novels/{novel_id}/story-guide/chapters/{chapter_number}")
async def get_story_guide_chapter_dossier(novel_id: int, chapter_number: int, through_chapter: int | None = Query(None, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    cutoff = _reader_safe_cutoff(db, current_user=current_user, metadata_novel_id=novel_id, requested_cutoff=through_chapter)
    return await metadata_client.get_story_guide_chapter_dossier(novel_id, chapter_number, cutoff)


@router.get("/novels/{novel_id}/story-guide/entities/{entity_id}")
async def get_story_guide_entity_article(novel_id: int, entity_id: str, through_chapter: int | None = Query(None, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    cutoff = _reader_safe_cutoff(db, current_user=current_user, metadata_novel_id=novel_id, requested_cutoff=through_chapter)
    return await metadata_client.get_story_guide_entity_article(novel_id, entity_id, cutoff)


@router.post("/novels/{novel_id}/story-guide/backfill")
async def backfill_story_guide(novel_id: int, current_user: User = Depends(get_current_user)):
    return await metadata_client.backfill_story_guide(novel_id)


@router.post("/novels/{novel_id}/story-guide/regenerate")
async def regenerate_story_guide(novel_id: int, through_chapter: int | None = Query(None, ge=0), db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    cutoff = _reader_safe_cutoff(db, current_user=current_user, metadata_novel_id=novel_id, requested_cutoff=through_chapter)
    return await metadata_client.regenerate_story_guide(novel_id, cutoff)


@router.post("/novels/{novel_id}/story-guide/characters/portrait")
async def create_story_guide_portrait(novel_id: int, payload: dict, current_user: User = Depends(get_current_user)):
    return await metadata_client.create_story_guide_portrait(novel_id, payload)


@router.get("/story-guide/media/{artifact_id}")
async def get_story_guide_media(artifact_id: str, current_user: User = Depends(get_current_user)):
    content, media_type = await metadata_client.get_story_guide_media(artifact_id)
    return Response(content, media_type=media_type, headers={"Cache-Control": "private, max-age=86400"})


@router.get("/novels/{novel_id}/editions")
async def get_novel_editions(novel_id: int, current_user: User = Depends(get_current_user)):
    return await metadata_client.get_canonical_work(novel_id)


@router.get("/sites/")
async def get_supported_sites(
    current_user: User = Depends(get_current_user),
):
    """Get list of supported sites."""
    return {
        "sites": [
            {"id": "royalroad", "name": "Royal Road"},
            {"id": "fanfiction", "name": "FanFiction.Net"},
            {"id": "spacebattles", "name": "SpaceBattles"},
            {"id": "archive", "name": "Archive of Our Own"},
            {"id": "webnovel", "name": "WebNovel"},
            {"id": "sufficientvelocity", "name": "Sufficient Velocity"},
            {"id": "questionablequesting", "name": "Questionable Questing"},
            {"id": "scribblehub", "name": "ScribbleHub"},
        ]
    }


@router.get("/fandoms/")
async def get_fandoms(
    site: Optional[str] = Query(None, description="Restrict to a source site"),
    media_type: Optional[str] = Query(None, description="Restrict to a source archive category"),
    q: Optional[str] = Query(None, description="Search canonical fandom names"),
    limit: int = Query(100, ge=1, le=250),
    current_user: User = Depends(get_current_user),
):
    """Expose persisted source fandoms without making the browser call metadata directly."""
    return await metadata_client.list_fandoms_metadata(
        site=site, media_type=media_type, query=q, limit=limit
    )
